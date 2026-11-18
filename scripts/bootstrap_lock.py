"""Warm bootstrap mutex; uses stdlib only and matches Vaani inference lease."""
import fcntl,json,os,pathlib,subprocess,sys
root=pathlib.Path(sys.argv[1]);path=root/".state/inference.lock";path.parent.mkdir(parents=True,exist_ok=True)
with path.open("a+") as lease:
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        message="Another Vaani inference/setup job is active; bootstrap did not modify files."
        print(message,file=sys.stderr)
        if "--json" in sys.argv:print(json.dumps(dict(status="failed",code=5,message=message,stage="bootstrap",job_directory=None,details={})))
        raise SystemExit(5)
    env=dict(os.environ,VAANI_BOOTSTRAP_LOCKED="1")
    raise SystemExit(subprocess.call(["/bin/sh",str(root/"scripts/bootstrap.sh"),*sys.argv[2:]],env=env))
