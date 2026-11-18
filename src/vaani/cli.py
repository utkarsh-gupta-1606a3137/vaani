import argparse,json,sys
from pathlib import Path
from . import __version__
from .types import VaaniError,SynthesisRequest
from .config import project_root,read

class Parser(argparse.ArgumentParser):
    def error(self,message):raise VaaniError(2,message)

def build_parser():
    p=Parser(prog="vaani",description="Local, project-contained Hinglish narration")
    p.add_argument("--version",action="version",version=__version__)
    sub=p.add_subparsers(dest="command",required=True)
    voices=sub.add_parser("voices");v=voices.add_subparsers(dest="voices_command",required=True)
    v.add_parser("list").add_argument("--json",action="store_true")
    doctor=sub.add_parser("doctor");doctor.add_argument("--json",action="store_true")
    setup=sub.add_parser("setup");setup.add_argument("--import-from","--from-test",dest="from_test",type=Path);setup.add_argument("--bootstrap-only",action="store_true");setup.add_argument("--allow-download",action="store_true");setup.add_argument("--json",action="store_true")
    status=sub.add_parser("status");status.add_argument("--job",type=Path,required=True);status.add_argument("--json",action="store_true")
    s=sub.add_parser("synthesize")
    s.add_argument("--input",type=Path);s.add_argument("--stdin",action="store_true");s.add_argument("--input-format",choices=["auto","text","markdown"],default="auto")
    s.add_argument("--voice");s.add_argument("--output",type=Path,required=True);s.add_argument("--format",choices=["wav","mp3"])
    s.add_argument("--normalization",choices=["audition-rms-v1","none"]);s.add_argument("--seed",type=int);s.add_argument("--overwrite",action="store_true")
    s.add_argument("--resume",type=Path);s.add_argument("--json",action="store_true")
    s.add_argument("--chunk-timeout",type=float,default=900);s.add_argument("--job-timeout",type=float,default=7200)
    return p

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv);machine="--json" in argv
    def progress(message):print(message,file=sys.stderr,flush=True)
    try:
        args=build_parser().parse_args(argv);root=project_root()
        if args.command in ("voices","doctor","setup"):
            from .setup import doctor,setup
            if args.command=="setup":result=setup(root,args.from_test,args.allow_download,progress,args.bootstrap_only)
            else:result=doctor(root)
            if args.command=="voices":result={"voices":result["voices"]}
            if machine:print(json.dumps(result,ensure_ascii=False))
            elif args.command=="voices":
                for voice in result["voices"]:print(f"{voice['id']}: {voice['display_name']} ({voice['gender']}, {voice['backend']}) — {'ready' if voice['available'] else 'setup required'}")
            else:print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if args.command=="voices" or result["status"] in ("ready","bootstrap_ready") else 4
        if args.command=="status":
            job=args.job.resolve()
            if not job.is_relative_to(root/"runs"):raise VaaniError(2,"Job path must belong to this Vaani project")
            try:result=read(job/"manifest.json")
            except (OSError,ValueError) as exc:raise VaaniError(2,"Cannot read job manifest") from exc
        else:
            if args.stdin and args.input is not None:raise VaaniError(2,"Use one input source")
            if args.stdin:
                raw=sys.stdin.buffer.read(1_000_001)
                if len(raw)>1_000_000:raise VaaniError(2,"Stdin input is too large")
                try:text=raw.decode("utf-8-sig")
                except UnicodeError as exc:raise VaaniError(2,"Stdin is not valid UTF-8") from exc
            else:text=None
            from .api import synthesize
            request=SynthesisRequest(output_path=args.output,input_path=args.input,text=text,input_format=args.input_format,
                                     voice_id=args.voice,output_format=args.format,normalization=args.normalization,
                                     seed=args.seed,overwrite=args.overwrite,resume_job_dir=args.resume,
                                     chunk_timeout_seconds=args.chunk_timeout,job_timeout_seconds=args.job_timeout)
            result=synthesize(request,root=root,progress=progress).to_dict()
        if machine:print(json.dumps(result,ensure_ascii=False))
        elif args.command=="status":print(json.dumps(result,ensure_ascii=False,indent=2))
        else:print(f"Saved {result['output_file']} ({result['duration_seconds']:.2f}s, {result['voice_id']})")
        return 0
    except KeyboardInterrupt:error=VaaniError(130,"Cancelled")
    except VaaniError as exc:error=exc
    except (OSError,ValueError,KeyError) as exc:error=VaaniError(4,"Operation could not complete: "+str(exc))
    if machine:print(json.dumps(error.to_dict(),ensure_ascii=False))
    else:print(f"Vaani error {error.code}: {error.message}",file=sys.stderr)
    return error.code
