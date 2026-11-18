import fcntl,json,os,time
from pathlib import Path
from .types import VaaniError

class Lease:
    def __init__(self,root):self.path=Path(root)/".state/inference.lock";self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open("a+")
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close();raise VaaniError(5,"Another Vaani inference job is active")
        self.file.seek(0);self.file.truncate();self.file.write(json.dumps(dict(pid=os.getpid(),started=time.time())));self.file.flush()
        return self
    def __exit__(self,*exc):
        if self.file:fcntl.flock(self.file,fcntl.LOCK_UN);self.file.close()

def available():
    import psutil
    return psutil.virtual_memory().available
