from pathlib import Path
from dataclasses import asdict
import json,os,signal,shutil,subprocess,tempfile,time,uuid
from .types import SynthesisRequest,SynthesisResult,VaaniError
from .config import project_root,environment,voice,identity,save,read,sha,fingerprint
from .input import read_source
from .chunking import plan,POLICY
from .resources import Lease,available,stop_process as _stop
from .audio import inspect,assemble,encode_mp3,verify_output

def output_path(path,fmt):
    p=Path(path).expanduser().resolve()
    suffix=p.suffix.lower()
    if fmt and fmt not in ("wav","mp3"):raise VaaniError(2,"Unsupported output format")
    if suffix and suffix not in (".wav",".mp3"):raise VaaniError(2,"Output extension must be .wav or .mp3")
    if fmt and suffix and suffix!="."+fmt:raise VaaniError(2,"Output extension conflicts with explicit format")
    fmt=fmt or suffix.lstrip(".") or "wav"
    if not suffix:p=p.with_suffix("."+fmt)
    return p,fmt

def _run_worker(root,profile,tasks,job,request,progress,started):
    import psutil
    if available()<9*1024**3:raise VaaniError(6,"Less than 9 GiB available; close memory-heavy applications and retry")
    status=job/"worker-status.json";status.unlink(missing_ok=True)
    packet=job/"worker-request.json"
    save(packet,dict(root=str(root),profile=profile,tasks=tasks,status_file=str(status)))
    exe=root/".runtime/envs"/profile["backend"]/"bin/python"
    telemetry=[];last_completed=-1;chunk_started=time.monotonic();last_heartbeat=0
    with (job/"worker.log").open("ab") as log:
        process=subprocess.Popen([str(exe),"-m","vaani.worker",str(packet)],stdout=log,stderr=log,env=environment(root),start_new_session=True)
        worker=psutil.Process(process.pid)
        try:
            while process.poll() is None:
                now=time.monotonic();state=read(status) if status.exists() else {}
                completed=state.get("completed",0)
                if completed!=last_completed:
                    if last_completed>=0:chunk_started=now
                    last_completed=completed;progress(f"Speech chunks complete: {completed}/{len(tasks)}")
                try:rss=worker.memory_info().rss
                except psutil.Error:rss=0
                free=available();telemetry.append(dict(elapsed_seconds=round(now-started,2),worker_rss_bytes=rss,system_available_bytes=free))
                if now-last_heartbeat>5:
                    save(job/"resource-telemetry.json",telemetry);last_heartbeat=now
                if free<1536*1024**2 or rss>10*1024**3:
                    raise VaaniError(6,"Speech worker stopped by memory guard")
                if now-chunk_started>request.chunk_timeout_seconds or now-started>request.job_timeout_seconds:
                    raise VaaniError(6,"Speech worker exceeded the configured timeout")
                time.sleep(.5)
            save(job/"resource-telemetry.json",telemetry)
            state=read(status) if status.exists() else {}
            if process.returncode or state.get("status")!="complete":
                raise VaaniError(7,"Speech generation failed; inspect worker.log",details={"worker_status":state.get("status"),"log_file":str(job/"worker.log")})
            return state
        except BaseException:
            _stop(process);save(job/"resource-telemetry.json",telemetry);raise

def _cache_valid(path,key):
    try:
        record=read(path.with_suffix(".json"))
        return record.get("cache_key")==key and sha(path)==record["sha256"] and bool(inspect(path))
    except (OSError,KeyError,ValueError,VaaniError):return False

def synthesize(request,*,root=None,progress=None):
    root=project_root(root);progress=progress or (lambda m:None);job=None;manifest=None;started=time.monotonic()
    try:
        if not isinstance(request,SynthesisRequest):raise VaaniError(2,"Expected SynthesisRequest")
        if not 1<=request.chunk_timeout_seconds<=7200 or not 1<=request.job_timeout_seconds<=86400:raise VaaniError(2,"Invalid timeout")
        output,fmt=output_path(request.output_path,request.output_format)
        for protected in ("models",".runtime","config","handoff","src","bin","locks","voices"):
            if output.is_relative_to(root/protected):raise VaaniError(2,"Output cannot replace project source or assets")
        if output.exists() and not request.overwrite:raise VaaniError(9,"Output exists; use --overwrite to replace it")
        if request.input_path is not None and Path(request.input_path).resolve()==output:raise VaaniError(2,"Output cannot replace input")
        restored=None
        if request.resume_job_dir:
            job=Path(request.resume_job_dir).resolve()
            if not job.is_relative_to(root/"runs"):raise VaaniError(2,"Resume job must belong to this Vaani project")
            try:restored=read(job/"manifest.json")
            except (OSError,ValueError) as exc:raise VaaniError(2,"Cannot read resume manifest") from exc
            stored=restored["request"]
            if request.voice_id is not None and request.voice_id!=stored["voice_id"]:raise VaaniError(2,"Resume voice differs from saved job")
            if request.seed is not None and request.seed!=stored["seed"]:raise VaaniError(2,"Resume seed differs from saved job")
            request.voice_id=stored["voice_id"];request.seed=stored["seed"]
            if request.input_path is None and request.text is None:
                request.text=(job/"input-original.txt").read_text();request.input_format=stored["input_format"]
        if request.word_timestamps is not None and not isinstance(request.word_timestamps,bool):raise VaaniError(2,"word_timestamps must be true, false or omitted")
        request.word_timestamps=request.word_timestamps if request.word_timestamps is not None else (restored['request'].get('word_timestamps',False) if restored else False)
        timestamps_output=output.with_suffix('.timestamps.json')
        if request.word_timestamps:
            if timestamps_output.exists() and not request.overwrite:raise VaaniError(9,"Timestamp output exists; use --overwrite to replace it")
            if request.input_path is not None and Path(request.input_path).resolve()==timestamps_output.resolve():raise VaaniError(2,"Timestamp output cannot replace input")
            if timestamps_output.is_symlink():raise VaaniError(2,"Timestamp output cannot replace a symlink")
        request.voice_id=request.voice_id or "amit"
        profile=voice(root,request.voice_id)
        request.seed=profile["default_seed"] if request.seed is None else request.seed
        if not isinstance(request.seed,int) or not 0<=request.seed<2**32:raise VaaniError(2,"Seed must be an unsigned 32-bit integer")
        original,prepared,mode=read_source(request)
        if restored and identity(prepared)!=restored["prepared_text_identity"]:raise VaaniError(2,"Resume input differs from saved job")
        try:chunks=plan(prepared)
        except ValueError as exc:raise VaaniError(2,str(exc)) from exc
        normalization=request.normalization or (restored["request"]["normalization"] if restored else "audition-rms-v1")
        if normalization not in ("none","audition-rms-v1"):raise VaaniError(2,"Unsupported normalization")
        with Lease(root):
            if request.word_timestamps:
                from .timestamps import preflight
                preflight(root)
            try:model_identity=fingerprint(root,profile)
            except (OSError,KeyError,ValueError) as exc:raise VaaniError(4,"Run vaani setup before synthesis: "+str(exc)) from exc
            if not (root/".runtime/envs"/profile["backend"]/"bin/python").exists():raise VaaniError(4,"Selected voice runtime missing; run setup")
            if fmt=="mp3" and not (root/".runtime/tools/ffmpeg").exists():raise VaaniError(4,"MP3 encoder missing; run setup")
            if job is None:job=root/"runs"/(time.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8])
            job.mkdir(parents=True,exist_ok=True)
            (job/"input-original.txt").write_text(original);(job/"spoken.txt").write_text(prepared)
            snapshot=dict(voice_id=request.voice_id,seed=request.seed,input_format=mode,normalization=normalization,output_format=fmt,output_file=str(output),word_timestamps=request.word_timestamps)
            boundary_warnings=[f"Chunk {c['index']+1} uses a bounded whitespace boundary; review its join." for c in chunks if c.get("boundary_basis")=="bounded_whitespace"]
            manifest=dict(schema_version="vaani-job/1",status="running",request=snapshot,prepared_text_identity=identity(prepared),model_identity=model_identity,voice_profile=profile,chunk_policy=POLICY,chunks=chunks,stage="planning",warnings=boundary_warnings)
            save(job/"manifest.json",manifest)
            tasks=[];paths=[];reused=0
            for chunk in chunks:
                seed=(request.seed+chunk["index"])%(2**32)
                key=identity(dict(text=chunk["text"],voice=request.voice_id,profile=profile,model_identity=model_identity,seed=seed,policy=POLICY))
                path=root/"cache/audio"/key/"raw.wav";paths.append(path)
                chunk.update(cache_key=key,seed=seed,cache_file=str(path))
                if _cache_valid(path,key):reused+=1;chunk["cache_reused"]=True
                else:tasks.append(dict(text=chunk["text"],seed=seed,cache_key=key,file=str(path)));chunk["cache_reused"]=False
            manifest["stage"]="speech";save(job/"manifest.json",manifest)
            if tasks:
                progress(f"Generating {len(tasks)} coherent chunk(s); reusing {reused}")
                manifest["worker"]=_run_worker(root,profile,tasks,job,request,progress,started)
            for path,chunk in zip(paths,chunks):
                if not _cache_valid(path,chunk["cache_key"]):raise VaaniError(7,"A speech chunk did not validate")
                chunk["media"]=inspect(path)
                if read(path.with_suffix(".json")).get("recovered_by_split"):
                    manifest["warnings"].append(f"Chunk {chunk['index']+1} required bounded split recovery; review its continuity.")
            manifest["stage"]="assembly";save(job/"manifest.json",manifest)
            assembled=job/"assembled.wav";manifest["assembly"]=assemble(paths,assembled,normalization);canonical=inspect(assembled)
            ffmpeg=root/".runtime/tools/ffmpeg";candidate=job/("candidate."+fmt)
            if fmt=="wav":shutil.copy2(assembled,candidate)
            else:encode_mp3(ffmpeg,assembled,candidate,job/"encoder.log")
            manifest["stage"]="verification";save(job/"manifest.json",manifest)
            media=verify_output(candidate,fmt,ffmpeg,job)
            if abs(media["duration_seconds"]-canonical["duration_seconds"])>(.2 if fmt=="mp3" else 1/24000):raise VaaniError(8,"Encoded output duration does not match assembled speech")
            timestamps_candidate=None;timestamps_reused=None
            if request.word_timestamps:
                manifest['stage']='word_timestamps';save(job/'manifest.json',manifest)
                from .timestamps import run_timestamps
                timestamps_candidate,timestamps_reused=run_timestamps(root,candidate,output.name,manifest['assembly']['chunks'],job,request,progress,started)
                manifest['word_timestamps']=dict(file=str(timestamps_output),sha256=sha(timestamps_candidate),cache_reused=timestamps_reused)
            result=SynthesisResult("complete",job,output,fmt,request.voice_id,media["duration_seconds"],media["sample_rate"],media["channels"],job/"manifest.json",reused>0,manifest["warnings"],timestamps_output if request.word_timestamps else None,timestamps_reused)
            manifest.update(status="complete",stage="complete",result=result.to_dict(),cache_reused_count=reused,generated_count=len(tasks),output_sha256=sha(candidate),elapsed_seconds=time.monotonic()-started)
            from .publication import publish
            def commit():
                if timestamps_candidate is None:save(job/"manifest.json",manifest)
                else:publish(timestamps_candidate,timestamps_output,request.overwrite,lambda:save(job/"manifest.json",manifest),manifest["warnings"])
            publish(candidate,output,request.overwrite,commit,manifest["warnings"])
            return result
    except BaseException as exc:
        if isinstance(exc,KeyboardInterrupt):error=VaaniError(130,"Narration cancelled; completed chunks are retained")
        elif isinstance(exc,VaaniError):error=exc
        elif isinstance(exc,OSError):error=VaaniError(9,"Filesystem operation failed: "+str(exc))
        else:error=VaaniError(7,"Narration failed: "+type(exc).__name__)
        if job and manifest:
            if manifest.get('stage')=='word_timestamps':
                candidate=job/('candidate.'+fmt)
                if candidate.is_file():error.details.setdefault('audio_file',str(candidate))
                error.stage=error.stage or 'word_timestamps'
            manifest.update(status="cancelled" if error.code==130 else "failed",error=error.to_dict(),elapsed_seconds=time.monotonic()-started)
            try:save(job/"manifest.json",manifest)
            except OSError:pass
        error.job_directory=str(job) if job else error.job_directory
        raise error from exc
