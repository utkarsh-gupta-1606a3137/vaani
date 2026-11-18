"""Project-contained installation from explicit pinned public sources."""
from pathlib import Path
import json,os,platform,shutil,subprocess,time,urllib.error,urllib.request
from .config import environment,registry,read,save,sha
from .types import VaaniError


def supported_host():
    try:major=int(platform.mac_ver()[0].split(".")[0])
    except (ValueError,IndexError):major=0
    return platform.system()=="Darwin" and platform.machine()=="arm64" and major>=26


def clone(source,target,*,symlinks=False):
    """Repair files from an explicitly supplied tree; never modify the source."""
    source=Path(source);target=Path(target)
    if source.is_dir():
        for p in source.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                clone(p,target/p.relative_to(source))
    else:
        if target.is_file() and sha(target)==sha(source):return
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_name(target.name+".importing")
        shutil.copy2(source.resolve(),temp);temp.replace(target)


def validate_file(path,record):
    return path.is_file() and path.stat().st_size==record["bytes"] and sha(path)==record["sha256"]


def download(url,target,record):
    """Stream to a disposable partial; publish only checksum-verified bytes."""
    if not url.startswith("https://huggingface.co/"):
        raise VaaniError(4,"Unapproved model download host")
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+".download")
    try:
        for attempt in range(3):
            try:
                request=urllib.request.Request(url,headers={"User-Agent":"Vaani/0.1"})
                with urllib.request.urlopen(request,timeout=120) as response,partial.open("wb") as out:
                    shutil.copyfileobj(response,out,8*1024*1024)
                if not validate_file(partial,record):raise VaaniError(4,"Pinned model checksum mismatch: "+target.name)
                partial.replace(target);return
            except (OSError,urllib.error.URLError) as exc:
                if attempt==2:raise VaaniError(4,"Model download failed: "+target.name+"; rerun setup to repair") from exc
                time.sleep(attempt+1)
    finally:
        partial.unlink(missing_ok=True)


def runtime_versions(root,name):
    pins=dict(line.strip().split("==",1) for line in (root/"locks"/(name+"-requirements.lock")).read_text().splitlines() if "==" in line)
    code="import importlib.metadata as m,json,sys; p=json.loads(sys.argv[1]); print(json.dumps({k:m.version(k) for k in p}))"
    try:
        result=subprocess.run([str(root/".runtime/envs"/name/"bin/python"),"-c",code,json.dumps(pins)],env=environment(root),capture_output=True,text=True,check=True,timeout=30)
        actual=json.loads(result.stdout)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        raise VaaniError(4,"Cannot validate pinned "+name+" runtime; rerun setup") from exc
    mismatches={k:{"expected":v,"installed":actual.get(k)} for k,v in pins.items() if actual.get(k)!=v}
    if mismatches:raise VaaniError(4,"Pinned runtime mismatch: "+name,details=mismatches)
    return actual


def sync_runtime(root,name,allow_download,progress):
    uv=root/".runtime/tools/uv";python=root/".runtime/python/bin/python3.12";target=root/".runtime/envs"/name
    env=environment(root,not allow_download)
    env.update(UV_OFFLINE="0" if allow_download else "1",UV_PYTHON_DOWNLOADS="never",UV_PYTHON_BIN_DIR=str(root/".runtime/tools"))
    log=root/"tmp"/("setup-"+name+".log")
    progress("Creating/checking pinned "+name+" runtime")
    # Re-create the venv shell on every setup to repair moved interpreter links, preserving packages.
    commands=[[str(uv),"venv","--allow-existing","--python",str(python),str(target)],
              [str(uv),"pip","sync","--python",str(target/"bin/python"),"--only-binary",":all:","--require-hashes","--index-url","https://pypi.org/simple",str(root/"locks"/(name+"-requirements.hashed.lock"))]]
    try:
        with log.open("w") as output:
            for cmd in commands:subprocess.run(cmd,env=env,stdout=output,stderr=output,check=True,timeout=1800)
    except (OSError,subprocess.SubprocessError) as exc:
        raise VaaniError(4,"Runtime setup failed; inspect "+str(log)+" and rerun setup") from exc
    runtime_versions(root,name)


def _setup(root,from_test=None,allow_download=False,progress=None,bootstrap_only=False):
    root=Path(root).resolve();progress=progress or (lambda message:None)
    if not supported_host():raise VaaniError(4,"Pinned MLX runtime requires Apple silicon macOS 26 or newer")
    environment(root)
    # The CLI shell bootstraps without requiring a preinstalled system Python.
    python=root/".runtime/python/bin/python3.12";uv=root/".runtime/tools/uv"
    if not python.is_file() or not uv.is_file():
        command=["/bin/sh",str(root/"scripts/bootstrap.sh")]
        if allow_download:command.append("--allow-download")
        try:subprocess.run(command,env=dict(os.environ,VAANI_BOOTSTRAP_LOCKED="1"),check=True,timeout=1800,stdout=None,stderr=None)
        except (OSError,subprocess.SubprocessError) as exc:raise VaaniError(4,"Portable bootstrap failed; rerun setup") from exc
    sync_runtime(root,"control",allow_download,progress)
    if bootstrap_only:
        return dict(status="bootstrap_ready",python_version="3.12.16",uv_version="0.13.9",project_root=str(root),models_installed=False)
    manifest=read(root/"config/downloads.json")
    source=Path(from_test).expanduser().resolve() if from_test else None
    if source==root:raise VaaniError(2,"Import source must differ from the destination project")
    if source is not None and not source.is_dir():raise VaaniError(4,"Explicit import source directory not found")
    files={}
    for relative,record in manifest["files"].items():
        path=Path(relative)
        if path.is_absolute() or ".." in path.parts:raise VaaniError(4,"Unsafe asset manifest path")
        target=root/path
        if not target.resolve().is_relative_to(root):raise VaaniError(4,"Asset symlink escapes project")
        if not validate_file(target,record):
            candidate=source/path if source else None
            if candidate is not None and validate_file(candidate,record):
                progress("Importing verified "+relative);clone(candidate,target)
            elif "url" in record and allow_download:
                progress("Downloading pinned "+relative);download(record["url"],target,record)
            elif "url" not in record:
                raise VaaniError(4,"Required tracked Amit conditioning reference is missing/corrupt; restore it from this repository")
            else:raise VaaniError(4,"Missing/corrupt asset "+relative+"; use --allow-download or --import-from INSTALLATION")
        if not validate_file(target,record):raise VaaniError(4,"Asset verification failed: "+relative)
        st=target.stat();files[relative]=dict(sha256=record["sha256"],bytes=st.st_size,mtime_ns=st.st_mtime_ns)
    for name in ("chatterbox","indic"):sync_runtime(root,name,allow_download,progress)
    for name in ("S3TokenizerV2","snac_24khz"):
        repo,revision=manifest["revisions"][name]
        cache=root/"cache/huggingface/hub"/("models--"+repo.replace("/","--"))
        (cache/"refs").mkdir(parents=True,exist_ok=True);(cache/"refs/main").write_text(revision)
        snapshot=cache/"snapshots"/revision;snapshot.parent.mkdir(parents=True,exist_ok=True)
        if snapshot.exists() or snapshot.is_symlink():
            if not snapshot.is_symlink():raise VaaniError(4,"Unexpected existing model cache directory: "+str(snapshot))
            snapshot.unlink()
        snapshot.symlink_to(os.path.relpath(root/"models"/name,snapshot.parent),target_is_directory=True)
    binary_dir=root/".runtime/envs/indic/lib/python3.12/site-packages/imageio_ffmpeg/binaries"
    binaries=[p for p in binary_dir.glob("ffmpeg-*") if p.is_file()]
    if len(binaries)!=1:raise VaaniError(4,"Expected one pinned imageio-ffmpeg executable")
    ffmpeg=root/".runtime/tools/ffmpeg";clone(binaries[0],ffmpeg);ffmpeg.chmod(0o755)
    encoder=subprocess.run([str(ffmpeg),"-hide_banner","-encoders"],capture_output=True,text=True,timeout=30)
    if encoder.returncode or "libmp3lame" not in encoder.stdout:raise VaaniError(4,"FFmpeg lacks libmp3lame")
    save(root/".state/assets.json",dict(schema_version="assets/1",files=files,revisions=manifest["revisions"],runtime_versions="locks/*-requirements.lock"))
    return doctor(root)

def doctor(root):
    root=Path(root);problems=[];voices=[]
    manifest=read(root/".state/assets.json") if (root/".state/assets.json").exists() else {"files":{}}
    for key,profile in registry(root)["voices"].items():
        missing=[]
        for asset in profile["assets"]+(["voices/references/amit-conditioning.wav"] if key=="amit" else []):
            p=root/asset;record=manifest["files"].get(asset)
            if not p.is_file() or not record:missing.append(asset)
            elif p.stat().st_size!=record["bytes"]:missing.append(asset+" (size mismatch)")
            elif p.stat().st_mtime_ns!=record["mtime_ns"] and sha(p)!=record["sha256"]:missing.append(asset+" (integrity mismatch)")
        exe=root/".runtime/envs"/profile["backend"]/"bin/python"
        if not exe.exists() or not exe.resolve().is_relative_to(root):missing.append("project-owned "+profile["backend"]+" Python")
        voices.append(dict(id=key,display_name=profile["display_name"],gender=profile["gender"],backend=profile["backend"],available=not missing,missing=missing))
    for p in [root/".runtime/envs/control/bin/python",root/".runtime/tools/ffmpeg"]:
        if not p.exists():problems.append("Missing "+str(p.relative_to(root)))
    external=[]
    for parent in [root/".runtime",root/"models",root/"cache/huggingface"]:
        if parent.exists():
            for p in parent.rglob("*"):
                if p.is_symlink() and not p.resolve().is_relative_to(root):external.append(str(p.relative_to(root)))
    problems.extend("External symlink: "+p for p in external)
    host=supported_host()
    if not host:problems.append("Apple silicon macOS 26 or newer is required")
    return dict(status="ready" if not problems and all(v["available"] for v in voices) else "not_ready",
                project_root=str(root),host_supported=host,voices=voices,problems=problems,
                offline_inference=True,model_import_check="not run: doctor does not initialize Metal or load models")


def setup(root,from_test=None,allow_download=False,progress=None,bootstrap_only=False):
    from .resources import Lease
    with Lease(root):
        return _setup(root,from_test,allow_download,progress,bootstrap_only)
