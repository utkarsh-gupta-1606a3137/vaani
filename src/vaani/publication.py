"""Atomic output publication with rollback if the job manifest cannot commit."""
from pathlib import Path
import os,shutil,tempfile,uuid
from .config import sha
from .types import VaaniError

def publish(candidate,output,overwrite,commit,warnings):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix="."+output.name+".",suffix=".pending",dir=output.parent);os.close(fd)
    backup=None;published=False;expected=sha(candidate)
    try:
        shutil.copyfile(candidate,temporary)
        with open(temporary,"rb") as f:os.fsync(f.fileno())
        if sha(temporary)!=expected:raise VaaniError(9,"Destination copy verification failed")
        if overwrite:
            if output.exists():
                backup=output.with_name("."+output.name+".vaani-backup-"+uuid.uuid4().hex)
                os.link(output,backup)
            os.replace(temporary,output)
        else:
            try:os.link(temporary,output)
            except FileExistsError as exc:raise VaaniError(9,"Output was created by another process; not overwriting") from exc
            os.unlink(temporary)
        published=True
        commit()
    except BaseException:
        if published:
            # Never remove/replace a different file written by an external actor.
            if output.is_file() and sha(output)==expected:
                if backup is not None:os.replace(backup,output);backup=None
                else:output.unlink()
            elif backup is not None:
                warnings.append("Previous output retained at "+str(backup))
        raise
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    if backup is not None:
        try:backup.unlink()
        except OSError:warnings.append("Old-output backup retained at "+str(backup))
