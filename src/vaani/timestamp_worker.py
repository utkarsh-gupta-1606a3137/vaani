"""One project-owned, offline MLX Whisper process; no speech-generation model is loaded."""
import json,os,socket,subprocess,sys,time,math,resource
from pathlib import Path
from .config import read,save,sha


def main():
    request=read(Path(sys.argv[1]));root=Path(request['root']);status=Path(request['status_file']);completed=0;started=time.monotonic()
    def offline(*args,**kwargs):raise RuntimeError('Network access is disabled in the Whisper worker')
    socket.socket.connect=offline;socket.create_connection=offline
    try:
        import numpy as np
        import mlx.core as mx
        import mlx_whisper
        mx.set_default_device(mx.gpu);mx.set_memory_limit(6*1024**3);mx.set_cache_limit(128*1024**2);mx.reset_peak_memory()
        save(status,dict(status='running',completed=0))
        audio=Path(request['audio'])
        if sha(audio)!=request['audio_sha256']:raise ValueError('Audio identity changed')
        # Decode the final candidate, including MP3 delay/padding handling, into the ASR clock.
        command=[str(root/'.runtime/tools/ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-i',str(audio),'-f','f32le','-acodec','pcm_f32le','-ac','1','-ar','16000','-']
        decoded=subprocess.run(command,capture_output=True,check=True,timeout=600).stdout
        samples=np.frombuffer(decoded,dtype=np.float32);duration=len(samples)/16000
        intervals=request['intervals'];segments=[];texts=[];warnings=['Word boundaries and probabilities are ASR estimates; no listening or forced-alignment verification was performed.']
        if abs(duration-intervals[-1]['end_seconds'])>.05:raise ValueError('Decoded audio does not match the assembly clock')
        prior_word=0.
        for interval in intervals:
            offset=interval['start_seconds'];end=interval['end_seconds'];clip=samples[round(offset*16000):round(end*16000)].copy()
            result=mlx_whisper.transcribe(clip,path_or_hf_repo=request['model'],language=request['language'],task='transcribe',word_timestamps=True,
                   condition_on_previous_text=False,temperature=(0.,.2,.4,.6),initial_prompt=request['initial_prompt'],verbose=None,fp16=True)
            texts.append(result.get('text','').strip())
            for segment in result.get('segments',[]):
                words=[]
                for word in segment.get('words',[]):
                    a=offset+float(word['start']);b=offset+float(word['end'])
                    if not math.isfinite(a+b) or a<offset-.05 or b>end+.05 or a>b:raise ValueError('Whisper returned an invalid word boundary')
                    a=max(offset,a);b=min(end,duration,b)
                    if a<prior_word:raise ValueError('Whisper word timings moved backwards')
                    prior_word=a
                    words.append(dict(word=word['word'],start=a,end=b,probability=float(word['probability']) if word.get('probability') is not None else None))
                if words:segments.append(dict(id=len(segments),chunk=interval['chunk'],start=words[0]['start'],end=words[-1]['end'],text=segment.get('text',''),words=words))
                if segment.get('compression_ratio',0)>2.4:warnings.append(f"Chunk {interval['chunk']} still has repetitive recognition; review before synchronization.")
            completed+=1
            save(status,dict(status='running',completed=completed,mlx_peak_bytes=mx.get_peak_memory()))
            mx.clear_cache()
        if sha(audio)!=request['audio_sha256']:raise ValueError('Audio identity changed during recognition')
        packet=dict(schema_version='vaani-word-timestamps/1',analysis_key=request['analysis_key'],audio=dict(filename='',sha256=request['audio_sha256'],duration_seconds=duration),
            model=dict(type='whisper',backend='mlx-whisper',fingerprint=request['model_fingerprint']),requested_language=request['language'] or 'auto',
            timing_basis='Estimated word timestamps; seconds from the named final audio recording start',text=' '.join(texts),segments=segments,
            chunks=intervals,warnings=warnings,metrics=dict(elapsed_seconds=time.monotonic()-started,mlx_peak_bytes=mx.get_peak_memory(),max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        save(request['output'],packet);save(status,dict(status='complete',completed=completed))
    except BaseException as exc:
        save(status,dict(status='failed',completed=completed,error_type=type(exc).__name__))
        raise


if __name__=='__main__':main()
