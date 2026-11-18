from pathlib import Path
import os,json,hashlib,tempfile
from .types import VaaniError

def project_root(root=None):
    return Path(root or os.environ.get("VAANI_ROOT") or Path(__file__).resolve().parents[2]).resolve()

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(8*1024*1024),b""):h.update(block)
    return h.hexdigest()

def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def read(path):return json.loads(Path(path).read_text())

def environment(root,offline=True):
    root=Path(root).resolve();env=dict(os.environ)
    paths={"UV_CACHE_DIR":"cache/uv","UV_PYTHON_INSTALL_DIR":".runtime/python-managed",
           "HF_HOME":"cache/huggingface","HF_HUB_CACHE":"cache/huggingface/hub",
           "HF_XET_CACHE":"cache/huggingface/xet","HF_ASSETS_CACHE":"cache/huggingface/assets",
           "TORCH_HOME":"cache/torch","XDG_CACHE_HOME":"cache/xdg","XDG_CONFIG_HOME":"cache/config",
           "XDG_DATA_HOME":"cache/data","PIP_CACHE_DIR":"cache/pip","MPLCONFIGDIR":"cache/matplotlib",
           "NUMBA_CACHE_DIR":"cache/numba","TMPDIR":"tmp","PYTHONPYCACHEPREFIX":"cache/pycache"}
    for key,relative in paths.items():
        p=root/relative;p.mkdir(parents=True,exist_ok=True);env[key]=str(p)
    env.update(VAANI_ROOT=str(root),PYTHONNOUSERSITE="1",HF_HUB_DISABLE_TELEMETRY="1",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1",HF_HUB_DISABLE_XET="1",DO_NOT_TRACK="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1",UV_NO_CONFIG="1",TOKENIZERS_PARALLELISM="false",
               OMP_NUM_THREADS="4",PYTHONPATH=str(root/"src"))
    env["HF_HUB_OFFLINE"]="1" if offline else "0"
    env["TRANSFORMERS_OFFLINE"]="1" if offline else "0"
    return env

def registry(root):return read(Path(root)/"config/voices.json")
def voice(root,voice_id):
    try:voices=registry(root)["voices"]
    except (OSError,ValueError,KeyError) as exc:raise VaaniError(4,"Voice registry is missing or invalid") from exc
    if voice_id not in voices:raise VaaniError(3,"Unknown voice ID. Available: "+", ".join(voices))
    return voices[voice_id]

def fingerprint(root,profile):
    manifest=read(Path(root)/".state/assets.json")
    required=profile["assets"]+["voices/references/amit-conditioning.wav"] if profile["backend"]=="chatterbox" else profile["assets"]
    selected={}
    for relative in required:
        p=Path(root)/relative;record=manifest["files"].get(relative)
        if not p.is_file() or not record:raise VaaniError(4,"Missing verified asset: "+relative)
        st=p.stat()
        if st.st_size!=record["bytes"] or st.st_mtime_ns!=record["mtime_ns"]:
            if sha(p)!=record["sha256"]:raise VaaniError(4,"Asset integrity changed: "+relative)
        selected[relative]=record["sha256"]
    # Include package locks and executable backend implementation in raw cache identity.
    for relative in ["src/vaani/worker.py","locks/"+profile["backend"]+"-requirements.lock"]:
        selected[relative]=sha(Path(root)/relative)
    return identity(selected)
