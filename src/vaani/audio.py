import audioop,math,os,subprocess,tempfile,wave
from pathlib import Path
from .types import VaaniError

def inspect(path):
    try:
        with wave.open(str(path),"rb") as f:
            channels,width,rate,frames=f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getnframes()
            pcm=f.readframes(frames)
        if channels!=1 or width!=2 or rate!=24000 or frames<2400 or len(pcm)!=frames*2:
            raise ValueError("Expected complete mono PCM16 24 kHz WAV")
        if audioop.max(pcm,2)<32:raise ValueError("Output is effectively silent")
        return dict(duration_seconds=frames/rate,sample_rate=rate,channels=channels,frames=frames,peak=audioop.max(pcm,2)/32768)
    except (OSError,ValueError,EOFError,wave.Error,audioop.error) as exc:
        raise VaaniError(7,"Invalid generated WAV: "+str(exc)) from exc

def write(path,pcm):
    with wave.open(str(path),"wb") as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm)

def assemble(paths,target,normalization):
    pieces=[];cues=[];cursor=0;joins=[]
    for index,path in enumerate(paths):
        inspect(path)
        with wave.open(str(path),"rb") as f:pcm=f.readframes(f.getnframes())
        gap=0
        if pieces:
            # Add only the missing quiet time, never cut consonants or overlap speech.
            def edge_quiet(data,reverse=False):
                frames=[data[i:i+480] for i in range(0,len(data),480)]
                if reverse:frames.reverse()
                count=0
                for frame in frames[:30]:
                    if len(frame)<2 or audioop.rms(frame,2)>98:break
                    count+=len(frame)//2
                return count
            existing=edge_quiet(pieces[-1],True)+edge_quiet(pcm)
            gap=max(0,2880-existing)
            if gap:pieces.append(bytes(gap*2));cursor+=gap
            joins.append(dict(before_chunk=index,added_silence_seconds=gap/24000,existing_quiet_seconds=existing/24000))
        start=cursor;pieces.append(pcm);cursor+=len(pcm)//2
        cues.append(dict(chunk=index,start_seconds=start/24000,end_seconds=cursor/24000,basis="measured chunk boundary; not word alignment"))
    pcm=b"".join(pieces);gain=1.0
    if normalization=="audition-rms-v1":
        squares=count=0
        for pos in range(0,len(pcm)-4799,4800):
            block=pcm[pos:pos+4800];rms=audioop.rms(block,2)/32768
            if rms>.005:squares+=rms*rms;count+=1
        if not count:raise VaaniError(7,"No active speech for normalization")
        gain=.06/math.sqrt(squares/count)
        peak=audioop.max(pcm,2)/32768
        if peak*gain>.98:gain=.98/peak
        pcm=audioop.mul(pcm,2,gain)
    elif normalization!="none":raise VaaniError(2,"Unsupported normalization profile")
    write(target,pcm)
    return dict(chunks=cues,joins=joins,gain_db=20*math.log10(gain),normalization=normalization)

def encode_mp3(ffmpeg,source,target,log):
    command=[str(ffmpeg),"-hide_banner","-loglevel","error","-nostdin","-y","-i",str(source),"-ac","1","-ar","24000","-c:a","libmp3lame","-b:a","128k","-f","mp3",str(target)]
    try:
        with Path(log).open("ab") as f:subprocess.run(command,stdout=f,stderr=f,check=True,timeout=600)
    except (OSError,subprocess.SubprocessError) as exc:raise VaaniError(8,"MP3 encoding failed; inspect encoder log") from exc

def verify_output(path,fmt,ffmpeg,work):
    if fmt=="wav":return inspect(path)
    decoded=Path(work)/"verify-decoded.wav"
    try:
        subprocess.run([str(ffmpeg),"-hide_banner","-loglevel","error","-nostdin","-y","-i",str(path),str(decoded)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=600)
        return inspect(decoded)
    except (OSError,subprocess.SubprocessError,VaaniError) as exc:raise VaaniError(8,"Encoded MP3 failed decoding/media verification") from exc
    finally:decoded.unlink(missing_ok=True)
