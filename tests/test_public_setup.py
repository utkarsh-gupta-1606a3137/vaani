"""Public-install contracts: no GPU and no network required."""
import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from vaani.config import sha
from vaani.resources import Lease
from vaani.setup import clone,download,validate_file,supported_host
from vaani.types import VaaniError
ROOT=Path(__file__).resolve().parents[1]

class PublicSetup(unittest.TestCase):
    def test_pinned_runtime_requires_supported_os_and_architecture(self):
        with patch("platform.system",return_value="Darwin"),patch("platform.machine",return_value="arm64"):
            with patch("platform.mac_ver",return_value=("15.7",("","",""),"")):self.assertFalse(supported_host())
            with patch("platform.mac_ver",return_value=("26.1",("","",""),"")):self.assertTrue(supported_host())
        with patch("platform.system",return_value="Linux"):self.assertFalse(supported_host())

    def test_all_runtime_assets_are_pinned_in_inventory(self):
        manifest=json.loads((ROOT/"config/downloads.json").read_text())
        voices=json.loads((ROOT/"config/voices.json").read_text())
        required={p for v in voices["voices"].values() for p in v["assets"]}
        required.add("voices/references/amit-conditioning.wav")
        self.assertEqual(required,set(manifest["files"]))
        for path,record in manifest["files"].items():
            self.assertFalse(Path(path).is_absolute());self.assertNotIn("..",Path(path).parts)
            self.assertEqual(len(record["sha256"]),64)
            if path.startswith("models/"):
                model=path.split("/")[1];repo,revision=manifest["revisions"][model]
                self.assertTrue(record["url"].startswith("https://huggingface.co/"+repo+"/resolve/"+revision+"/"))
        for suffix in ["vocos/load.py","vocos/__init__.py"]:
            self.assertIn("models/indic-speak-mlx-8bit/"+suffix,required)

    def test_required_synthetic_conditioning_is_shipped_and_verified(self):
        record=json.loads((ROOT/"config/downloads.json").read_text())["files"]["voices/references/amit-conditioning.wav"]
        self.assertTrue(validate_file(ROOT/"voices/references/amit-conditioning.wav",record))

    def test_checksum_failure_preserves_existing_target_and_cleans_partial(self):
        import io
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as folder:
            target=Path(folder)/"asset";target.write_bytes(b"old")
            record={"bytes":4,"sha256":hashlib.sha256(b"good").hexdigest()}
            with patch("urllib.request.urlopen",return_value=io.BytesIO(b"evil")):
                with self.assertRaises(VaaniError):download("https://huggingface.co/model/resolve/revision/asset",target,record)
            self.assertEqual(target.read_bytes(),b"old");self.assertFalse(target.with_name("asset.download").exists())

    def test_successful_download_verifies_before_publication(self):
        import io
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as folder:
            target=Path(folder)/"asset";record={"bytes":4,"sha256":hashlib.sha256(b"good").hexdigest()}
            with patch("urllib.request.urlopen",return_value=io.BytesIO(b"good")):
                download("https://huggingface.co/model/resolve/revision/asset",target,record)
            self.assertTrue(validate_file(target,record))

    def test_download_rejects_unapproved_hosts(self):
        with self.assertRaises(VaaniError):download("https://example.com/asset",ROOT/"tmp/unused",{})

    def test_warm_bootstrap_respects_inference_lease_without_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as folder:
            root=Path(folder);(root/"scripts").mkdir()
            # The callback would visibly run if the helper failed to acquire the shared lease.
            marker=root/"MUTATED"
            (root/"scripts/bootstrap.sh").write_text("#!/bin/sh\ntouch "+str(marker)+"\n")
            with Lease(root):
                result=subprocess.run([str(ROOT/".runtime/envs/control/bin/python"),str(ROOT/"scripts/bootstrap_lock.py"),str(root)],capture_output=True,text=True)
            self.assertEqual(result.returncode,5);self.assertFalse(marker.exists())

    def test_cold_bootstrap_without_download_permission_returns_json(self):
        import shutil
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as folder:
            root=Path(folder);(root/"scripts").mkdir()
            shutil.copy2(ROOT/"scripts/bootstrap.sh",root/"scripts/bootstrap.sh")
            result=subprocess.run(["/bin/sh",str(root/"scripts/bootstrap.sh"),"--json"],capture_output=True,text=True)
            self.assertEqual(result.returncode,4,result.stderr)
            self.assertEqual(json.loads(result.stdout)["stage"],"bootstrap")
            self.assertFalse((root/".runtime/python").exists())
            self.assertFalse((root/".state/bootstrap.lock").exists())

    def test_unsupported_host_returns_json_before_any_runtime_write(self):
        import shutil
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as folder:
            root=Path(folder);(root/"scripts").mkdir();(root/"fakebin").mkdir()
            shutil.copy2(ROOT/"scripts/bootstrap.sh",root/"scripts/bootstrap.sh")
            uname=root/"fakebin/uname";uname.write_text("#!/bin/sh\nprintf Linux\n");uname.chmod(0o755)
            env=dict(os.environ,PATH=str(root/"fakebin")+":/usr/bin:/bin")
            result=subprocess.run(["/bin/sh",str(root/"scripts/bootstrap.sh"),"--json"],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,4)
            self.assertEqual(json.loads(result.stdout)["code"],4)
            self.assertFalse((root/".runtime").exists())

    def test_artifact_hash_locks_preserve_exact_plain_version_pins(self):
        import re
        for name in ["control","chatterbox","indic"]:
            plain=(ROOT/"locks"/(name+"-requirements.lock")).read_text()
            hashed=(ROOT/"locks"/(name+"-requirements.hashed.lock")).read_text()
            pins=lambda text:dict(line.split()[0].split("==",1) for line in text.splitlines() if line and "==" in line and not line.lstrip().startswith("#"))
            self.assertEqual(pins(plain),pins(hashed))
            lines=hashed.splitlines()
            for pin in plain.splitlines():
                if "==" in pin:
                    index=next(i for i,line in enumerate(lines) if line.startswith(pin+" "))
                    self.assertRegex(lines[index+1].strip(),r"^--hash=sha256:[a-f0-9]{64}")

    def test_bootstrap_archive_pins_are_literal_and_staged(self):
        shell=(ROOT/"scripts/bootstrap.sh").read_text()
        self.assertIn("5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca",shell)
        self.assertIn("2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd",shell)
        self.assertLess(shell.index('"$STAGE/python/bin/python3.12" -c'),shell.index('mv "$STAGE/python"'))
        self.assertIn(".vaani-bootstrap-complete",shell)

if __name__=="__main__":unittest.main()
