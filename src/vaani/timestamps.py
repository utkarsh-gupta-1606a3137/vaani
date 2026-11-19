"""Optional offline word timings; the lightweight controller never imports MLX."""
from pathlib import Path
import json,math,os,subprocess,time
from .config import environment,identity,read,save,sha,whisper_settings
from .resources import Lease,available,stop_process
from .types import VaaniError

SCHEMA='vaani-word-timestamps/1'


def preflight(root,*,runtime=True):
    root=Path(root);settings=whisper_settings(root);model=settings['model_path']
    weights=next((model/name for name in ('weights.safetensors','weights.npz') if (model/name).is_file()),None)
    try:config=read(model/'config.json')
    except (OSError,ValueError) as exc:raise VaaniError(4,'Local Whisper model missing/invalid; set whisper.model_path in config/voices.local.json') from exc
    required=('n_mels','n_audio_ctx','n_audio_state','n_audio_head','n_audio_layer','n_vocab','n_text_ctx','n_text_state','n_text_head','n_text_layer')
    if weights is None or weights.stat().st_size<=0 or weights.stat().st_size>6*1024**3 or not all(isinstance(config.get(k),int) and config[k]>0 for k in required):
        raise VaaniError(4,'Expected local MLX Whisper weights and configuration (at most 6 GiB of weights)')
    if not (root/'.runtime/tools/ffmpeg').is_file():raise VaaniError(4,'Project FFmpeg missing; run the normal Vaani setup')
    if runtime and not (root/'.runtime/envs/whisper/bin/python').is_file():raise VaaniError(4,'Whisper runtime missing; run vaani setup --word-timestamps')
    return settings,weights


def doctor_timestamps(root):
    try:
        settings,_=preflight(root)
        return dict(status='ready',component='word_timestamps',model_path=str(settings['model_path']),offline_inference=True,model_import_check='not run: doctor does not initialize Metal')
    except VaaniError as exc:return dict(status='not_ready',component='word_timestamps',problems=[exc.message])


def setup_timestamps(root,allow_download=False,progress=None):
    """Install only the optional runtime. Model files are supplied locally, never downloaded here."""
    root=Path(root);progress=progress or (lambda message:None)
    with Lease(root):
        preflight(root,runtime=False)
        uv=root/'.runtime/tools/uv';python=root/'.runtime/python/bin/python3.12';target=root/'.runtime/envs/whisper'
        if not uv.is_file() or not python.is_file():raise VaaniError(4,'Run the normal Vaani setup before adding word timestamps')
        env=environment(root,not allow_download)
        env.update(UV_OFFLINE='0' if allow_download else '1',UV_PYTHON_DOWNLOADS='never')
        commands=[[str(uv),'venv','--allow-existing','--python',str(python),str(target)],
                  [str(uv),'pip','sync','--python',str(target/'bin/python'),'--only-binary',':all:','--require-hashes','--index-url','https://pypi.org/simple',str(root/'locks/whisper-requirements.hashed.lock')]]
        log=root/'tmp/setup-whisper.log';progress('Installing/checking optional pinned Whisper runtime')
        try:
            with log.open('w') as output:
                for command in commands:subprocess.run(command,env=env,stdout=output,stderr=output,check=True,timeout=1800)
            pins=dict(line.split('==',1) for line in (root/'locks/whisper-requirements.lock').read_text().splitlines() if line and not line.startswith('#'))
            check='import importlib.metadata as m,json,sys; p=json.loads(sys.argv[1]); assert all(m.version(k)==v for k,v in p.items())'
            subprocess.run([str(target/'bin/python'),'-c',check,json.dumps(pins)],env=env,check=True,capture_output=True,timeout=30)
        except (OSError,subprocess.SubprocessError) as exc:raise VaaniError(4,'Whisper runtime setup failed; inspect '+str(log)) from exc
        return doctor_timestamps(root)


def validate_packet(packet,audio_hash,key,duration):
    if packet.get('schema_version')!=SCHEMA or packet.get('analysis_key')!=key:raise ValueError('Timestamp identity mismatch')
    media=packet['audio']
    if media['sha256']!=audio_hash or abs(media['duration_seconds']-duration)>.05:raise ValueError('Timestamp audio mismatch')
    if not isinstance(packet.get('text'),str) or not isinstance(packet.get('segments'),list):raise ValueError('Invalid recognition packet')
    prior=0.;count=0
    for segment in packet['segments']:
        for word in segment['words']:
            a,b=word['start'],word['end'];prob=word.get('probability')
            if not isinstance(word['word'],str) or not word['word'].strip():raise ValueError('Empty recognized word')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (a,b)):raise ValueError('Non-finite word timing')
            if not 0<=a<=b<=duration+.001 or a<prior:raise ValueError('Unordered or out-of-range word timing')
            if prob is not None and (isinstance(prob,bool) or not isinstance(prob,(int,float)) or not math.isfinite(prob) or not 0<=prob<=1):raise ValueError('Invalid word probability')
            prior=a;count+=1
    if not count:raise ValueError('No word timings were produced')
    return count


def run_timestamps(root,audio,output_name,intervals,job,request,progress,started):
    """Called only after the speech worker exits; caller holds the project inference lease."""
    import psutil
    root=Path(root);audio=Path(audio);settings,weights=preflight(root)
    if time.monotonic()-started>=request.job_timeout_seconds:raise VaaniError(6,'Job timeout reached before word timestamps',stage='word_timestamps')
    audio_hash=sha(audio)
    # Keep paths in private worker requests, never in the shareable sidecar.
    model_fingerprint=identity(dict(config_sha256=sha(settings['model_path']/'config.json'),weights_sha256=sha(weights)))
    key=identity(dict(audio_sha256=audio_hash,model=model_fingerprint,language=settings['language'],initial_prompt=settings['initial_prompt'],intervals=intervals,
                      implementation=sha(root/'src/vaani/timestamp_worker.py'),dependencies=sha(root/'locks/whisper-requirements.lock')))
    cache=root/'cache/word-timestamps'/key/'result.json';candidate=job/'word-timestamps.json'
    try:
        packet=read(cache)
        if sha(cache)!=read(cache.with_suffix('.sha256.json'))['sha256']:raise ValueError('Corrupt timestamp cache')
        validate_packet(packet,audio_hash,key,intervals[-1]['end_seconds'])
    except (OSError,ValueError,KeyError,TypeError):packet=None
    reused=packet is not None
    if packet is None:
        if available()<6*1024**3:raise VaaniError(6,'Less than 6 GiB available for the Whisper worker',stage='word_timestamps')
        status=job/'timestamps-status.json';status.unlink(missing_ok=True)
        worker_request=job/'timestamps-request.json'
        save(worker_request,dict(root=str(root),audio=str(audio),model=str(settings['model_path']),language=settings['language'],initial_prompt=settings['initial_prompt'],intervals=intervals,
             output=str(candidate),status_file=str(status),audio_sha256=audio_hash,analysis_key=key,model_fingerprint=model_fingerprint))
        telemetry=[];last_done=-1;chunk_started=time.monotonic();heartbeat=0
        with (job/'timestamps-worker.log').open('ab') as log:
            process=subprocess.Popen([str(root/'.runtime/envs/whisper/bin/python'),'-m','vaani.timestamp_worker',str(worker_request)],stdout=log,stderr=log,env=environment(root),start_new_session=True)
            worker=psutil.Process(process.pid)
            try:
                while process.poll() is None:
                    now=time.monotonic();state=read(status) if status.exists() else {};done=state.get('completed',0)
                    if done!=last_done:
                        last_done=done;chunk_started=now;progress(f'Word-timestamp chunks complete: {done}/{len(intervals)}')
                    try:rss=worker.memory_info().rss
                    except psutil.Error:rss=0
                    free=available();telemetry.append(dict(elapsed_seconds=round(now-started,2),worker_rss_bytes=rss,system_available_bytes=free))
                    if rss>8*1024**3 or free<1536*1024**2:raise VaaniError(6,'Whisper worker stopped by memory guard',stage='word_timestamps')
                    if now-started>request.job_timeout_seconds or now-chunk_started>request.chunk_timeout_seconds:raise VaaniError(6,'Whisper worker exceeded the configured timeout',stage='word_timestamps')
                    if now-heartbeat>5:save(job/'timestamps-telemetry.json',telemetry);heartbeat=now
                    time.sleep(.25)
                state=read(status) if status.exists() else {}
                if process.returncode or state.get('status')!='complete':raise VaaniError(8,'Word timestamps failed; inspect timestamps-worker.log',stage='word_timestamps',details={'audio_file':str(audio)})
            except BaseException:
                stop_process(process);raise
            finally:save(job/'timestamps-telemetry.json',telemetry)
        try:
            packet=read(candidate);validate_packet(packet,audio_hash,key,intervals[-1]['end_seconds'])
        except (OSError,ValueError,KeyError,TypeError) as exc:raise VaaniError(8,'Word timestamp output failed validation; generated audio remains in the job directory',stage='word_timestamps') from exc
        if sha(audio)!=audio_hash:raise VaaniError(8,'Audio changed during word-timestamp generation',stage='word_timestamps')
        save(cache,packet);save(cache.with_suffix('.sha256.json'),{'sha256':sha(cache)})
    if sha(audio)!=audio_hash:raise VaaniError(8,'Audio changed while preparing word timestamps',stage='word_timestamps')
    packet['audio']['filename']=output_name
    save(candidate,packet)
    return candidate,reused
