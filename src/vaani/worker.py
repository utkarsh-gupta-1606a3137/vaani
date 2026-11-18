"""Isolated offline speech worker. Communicates completion through atomic files."""
from pathlib import Path
import hashlib,json,os,sys,time,traceback,wave
from .config import read,save,sha
from .audio import inspect,assemble

def main():
    request=read(sys.argv[1]);root=Path(request["root"]);profile=request["profile"]
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    mx.set_memory_limit(8*1024**3);mx.set_cache_limit(256*1024**2)
    started=time.monotonic();status=Path(request["status_file"])
    if profile["backend"]=="chatterbox":
        from mlx_audio.tts.models.chatterbox.chatterbox import Model
        model=Model.from_pretrained(root/"models/chatterbox-multilingual-v3",s3_tokenizer_repo="mlx-community/S3TokenizerV2")
        raw_inference=model.t3.inference;evidence={}
        def tracked(*args,**kwargs):
            ids=raw_inference(*args,**kwargs);mx.eval(ids)
            values=np.asarray(ids)
            row=values[0].reshape(-1)
            evidence.update(speech_tokens=int(row.size),ended=bool(row.size and int(row[-1])==int(model.t3.hp.stop_speech_token)))
            return ids
        model.t3.inference=tracked
        def generate(text,seed):
            mx.random.seed(seed);evidence.clear()
            results=list(model.generate(text=text,audio_prompt=str(root/"voices/references/amit-conditioning.wav"),audio_prompt_sr=24000,**profile["settings"]))
            if len(results)!=1 or not evidence.get("ended"):raise ValueError("Incomplete speech generation (no stop token)")
            return np.asarray(results[0].audio,dtype=np.float32).reshape(-1),dict(evidence)
    else:
        import torch
        torch.set_num_threads(4)
        sys.path.insert(0,str(root/"models/indic-speak-mlx-8bit"))
        from tts_mlx import MLXTTS
        model=MLXTTS(root/"models/indic-speak-mlx-8bit",decode_device="cpu")
        def generate(text,seed):
            wav,stats=model(text,seed=seed,**profile["settings"])
            if stats.get("hit_cap"):raise ValueError("Incomplete speech generation (token cap)")
            return np.asarray(wav,dtype=np.float32).reshape(-1),stats
    save(status,dict(status="loaded",completed=0,total=len(request["tasks"])))
    for number,task in enumerate(request["tasks"]):
        attempts=[];target=Path(task["file"]);target.parent.mkdir(parents=True,exist_ok=True)
        def piece(text,seed,path):
            wav,stats=generate(text,seed)
            if not wav.size or not np.isfinite(wav).all() or float(np.max(np.abs(wav)))<.001:raise ValueError("Invalid waveform")
            duration=len(wav)/24000
            if duration<max(.1,len(text.split())*.07) or duration>max(10,len(text.split())*1.25+3):raise ValueError("Implausible speech duration")
            peak=float(np.max(np.abs(wav)))
            if peak>.99:wav*=.99/peak
            sf.write(path,wav,24000,subtype="PCM_16");inspect(path)
            return stats
        temporary=target.with_suffix(".generating.wav");stats=None;split=False
        for trial in range(2):
            try:
                stats=piece(task["text"],task["seed"],temporary);attempts.append(dict(attempt=trial+1,status="complete"));break
            except (ValueError,RuntimeError) as exc:
                attempts.append(dict(attempt=trial+1,status="failed",reason=str(exc)))
                temporary.unlink(missing_ok=True)
        if stats is None:
            # Two complete attempts plus at most two half-utterance attempts.
            import re
            words=task["text"].split()
            if len(words)<6:raise ValueError("Speech chunk failed bounded retries")
            candidates=[m.end() for m in re.finditer(r"[.!?।,;:]\s+",task["text"])]
            middle=min(candidates,key=lambda p:abs(p-len(task["text"])/2)) if candidates else len(" ".join(words[:len(words)//2]))
            texts=[task["text"][:middle].strip(),task["text"][middle:].strip()]
            if not all(texts):raise ValueError("No safe bounded recovery boundary")
            child_paths=[];child_stats=[]
            for child,text in enumerate(texts):
                p=target.with_name(target.stem+f".recovery-{child}.wav")
                child_stats.append(piece(text,(task["seed"]+101+child)%(2**32),p));child_paths.append(p)
            assembly=assemble(child_paths,temporary,"none")
            for p in child_paths:p.unlink(missing_ok=True)
            stats=dict(recovered_by_split=True,children=child_stats,assembly=assembly);split=True
        temporary.replace(target)
        info=inspect(target)
        record=dict(cache_key=task["cache_key"],text_sha256=hashlib.sha256(task["text"].encode()).hexdigest(),seed=task["seed"],sha256=sha(target),media=info,statistics=stats,attempts=attempts,recovered_by_split=split)
        save(target.with_suffix(".json"),record)
        save(status,dict(status="running",completed=number+1,total=len(request["tasks"]),last_file=str(target),elapsed_seconds=time.monotonic()-started,mlx_peak_gb=mx.get_peak_memory()/1e9))
    save(status,dict(status="complete",completed=len(request["tasks"]),total=len(request["tasks"]),elapsed_seconds=time.monotonic()-started,mlx_peak_gb=mx.get_peak_memory()/1e9))

if __name__=="__main__":
    try:main()
    except BaseException as exc:
        traceback.print_exc()
        try:
            request=read(sys.argv[1]);save(request["status_file"],dict(status="failed",message=type(exc).__name__,reason=str(exc)))
        except Exception:pass
        raise SystemExit(7)
