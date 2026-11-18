import json,os,subprocess,sys,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
from vaani.types import SynthesisRequest,VaaniError
from vaani.config import save,sha
from vaani.input import prepare
from vaani.chunking import plan
from vaani.audio import inspect,assemble
from vaani.api import synthesize,output_path
from vaani.setup import clone

class EngineContracts(unittest.TestCase):
    def test_output_format_and_protection(self):
        self.assertEqual(output_path("sample",None)[1],"wav")
        self.assertEqual(output_path("sample.mp3",None)[1],"mp3")
        with self.assertRaises(VaaniError):output_path("sample.mp3","wav")
    def test_setup_repairs_missing_copied_asset_without_overwriting_valid_neighbor(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source";target=Path(d)/"target"
            source.mkdir();target.mkdir();(source/"first").write_text("same");(source/"missing").write_text("needed")
            (target/"first").write_text("same");before=(target/"first").stat().st_mtime_ns
            clone(source,target)
            self.assertEqual((target/"missing").read_text(),"needed")
            self.assertEqual((target/"first").stat().st_mtime_ns,before)
    def test_inline_pipe_is_not_mistaken_for_a_table(self):
        self.assertEqual(prepare("Use `a|b` or a | b in the explanation.","markdown"),"Use a|b or a | b in the explanation.")
    def test_setup_repairs_corrupt_copied_asset(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source";target=Path(d)/"target";source.mkdir();target.mkdir()
            (source/"asset").write_bytes(b'good');(target/"asset").write_bytes(b'bad!')
            clone(source,target);self.assertEqual((target/"asset").read_bytes(),b'good')
    def test_input_failures(self):
        for text in ["", chr(0), "<|start_of_speech|>"]:
            with self.subTest(text=text),self.assertRaises(VaaniError):prepare(text)
        with self.assertRaises(VaaniError):prepare("|a|b|\n|-|-|","markdown")
    def test_core_cache_resume_and_output_atomicity(self):
        import math,struct
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"config").mkdir();(root/".runtime/envs/chatterbox/bin").mkdir(parents=True)
            (root/".runtime/envs/chatterbox/bin/python").touch()
            profile={"backend":"chatterbox","default_seed":42,"assets":[],"settings":{},"profile_version":"test"}
            save(root/"config/voices.json",{"voices":{"amit":profile}})
            calls=[]
            def fake_worker(root,profile,tasks,job,request,progress,started):
                calls.append(len(tasks))
                for task in tasks:
                    p=Path(task['file']);p.parent.mkdir(parents=True,exist_ok=True)
                    pcm=b''.join(struct.pack('<h',int(5000*math.sin(2*math.pi*200*i/24000))) for i in range(24000))
                    with wave.open(str(p),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm)
                    save(p.with_suffix('.json'),dict(cache_key=task['cache_key'],sha256=sha(p)))
                return {"status":"complete"}
            with patch('vaani.api.fingerprint',return_value='model-test'),patch('vaani.api._run_worker',side_effect=fake_worker):
                result=synthesize(SynthesisRequest(output_path=root/'one.wav',text='First complete paragraph.\n\nSecond complete paragraph.'),root=root)
                self.assertEqual(calls,[2]);self.assertEqual(inspect(result.output_file)['sample_rate'],24000)
                resumed=synthesize(SynthesisRequest(output_path=root/'two.wav',resume_job_dir=result.job_directory),root=root)
                self.assertEqual(calls,[2]);self.assertTrue(resumed.cache_reused)
                # Corrupt exactly one cached chunk; its neighbor survives.
                manifest=json.loads(result.manifest_file.read_text());p=Path(manifest['chunks'][0]['cache_file']);p.write_bytes(b'bad')
                repaired=synthesize(SynthesisRequest(output_path=root/'three.wav',text='First complete paragraph.\n\nSecond complete paragraph.'),root=root)
                self.assertEqual(calls,[2,1]);self.assertTrue(repaired.cache_reused)
                original=(root/'one.wav').read_bytes()
                with self.assertRaises(VaaniError):synthesize(SynthesisRequest(output_path=root/'one.wav',text='Different content'),root=root)
                self.assertEqual((root/'one.wav').read_bytes(),original)
                with self.assertRaises(VaaniError):synthesize(SynthesisRequest(output_path=root/'four.wav',text='Different content',resume_job_dir=result.job_directory),root=root)
    def test_cli_json_error_is_single_parseable_result(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([str(root/'bin/vaani'),'synthesize','--input','missing.txt','--output','irrelevant.wav','--voice','missing','--json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,3);data=json.loads(result.stdout);self.assertEqual(data['status'],'failed')

    def test_cancelled_job_restores_saba_normalization_and_reuses_completed_chunk(self):
        import math,struct
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();(root/'.runtime/envs/indic/bin').mkdir(parents=True)
            (root/'.runtime/envs/indic/bin/python').touch()
            profile={'backend':'indic','default_seed':1234,'assets':[],'settings':{},'profile_version':'test'}
            save(root/'config/voices.json',{'voices':{'saba':profile}})
            def fill(task):
                p=Path(task['file']);p.parent.mkdir(parents=True,exist_ok=True)
                pcm=b''.join(struct.pack('<h',int(4000*math.sin(2*math.pi*180*i/24000))) for i in range(12000))
                with wave.open(str(p),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm)
                save(p.with_suffix('.json'),{'cache_key':task['cache_key'],'sha256':sha(p)})
            def interrupted(root,profile,tasks,job,request,progress,started):fill(tasks[0]);raise KeyboardInterrupt
            with patch('vaani.api.fingerprint',return_value='test-model'),patch('vaani.api._run_worker',side_effect=interrupted):
                with self.assertRaises(VaaniError) as caught:
                    synthesize(SynthesisRequest(output_path=root/'cancelled.wav',text='First paragraph.\n\nSecond paragraph.',voice_id='saba',normalization='none'),root=root)
            self.assertEqual(caught.exception.code,130)
            job=Path(caught.exception.job_directory);self.assertEqual(json.loads((job/'manifest.json').read_text())['status'],'cancelled')
            remaining=[]
            def resumed(root,profile,tasks,job,request,progress,started):
                remaining.extend(tasks)
                for task in tasks:fill(task)
                return {'status':'complete'}
            with patch('vaani.api.fingerprint',return_value='test-model'),patch('vaani.api._run_worker',side_effect=resumed):
                result=synthesize(SynthesisRequest(output_path=root/'resumed.wav',resume_job_dir=job),root=root)
            self.assertEqual(len(remaining),1);self.assertEqual(result.voice_id,'saba');self.assertTrue(result.cache_reused)
            self.assertEqual(json.loads(result.manifest_file.read_text())['assembly']['normalization'],'none')

    def test_failed_overwrite_preserves_original_and_cached_speech(self):
        import math,struct
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();(root/'.runtime/envs/chatterbox/bin').mkdir(parents=True)
            (root/'.runtime/envs/chatterbox/bin/python').touch()
            save(root/'config/voices.json',{'voices':{'amit':{'backend':'chatterbox','default_seed':42,'assets':[],'settings':{},'profile_version':'test'}}})
            target=root/'output.wav';target.write_bytes(b'existing user output')
            def fill(root,profile,tasks,job,request,progress,started):
                for task in tasks:
                    p=Path(task['file']);p.parent.mkdir(parents=True,exist_ok=True)
                    pcm=b''.join(struct.pack('<h',int(4000*math.sin(2*math.pi*180*i/24000))) for i in range(12000))
                    with wave.open(str(p),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm)
                    save(p.with_suffix('.json'),{'cache_key':task['cache_key'],'sha256':sha(p)})
                return {'status':'complete'}
            with patch('vaani.api.fingerprint',return_value='test-model'),patch('vaani.api._run_worker',side_effect=fill) as worker:
                with patch('vaani.api.verify_output',side_effect=VaaniError(8,'deliberate verification failure')):
                    with self.assertRaises(VaaniError) as caught:synthesize(SynthesisRequest(output_path=target,text='Some complete speech.',overwrite=True),root=root)
                self.assertEqual(caught.exception.code,8);self.assertEqual(target.read_bytes(),b'existing user output')
                result=synthesize(SynthesisRequest(output_path=target,text='Some complete speech.',overwrite=True),root=root)
                self.assertEqual(worker.call_count,1);self.assertTrue(result.cache_reused);inspect(target)

    def test_long_single_token_is_typed_input_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir()
            save(root/'config/voices.json',{'voices':{'amit':{'backend':'chatterbox','default_seed':42}}})
            with self.assertRaises(VaaniError) as caught:synthesize(SynthesisRequest(output_path=root/'x.wav',text='x'*451),root=root)
            self.assertEqual(caught.exception.code,2)

    def test_late_manifest_failure_rolls_back_overwrite(self):
        from vaani.publication import publish
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'candidate.wav';output=root/'user.wav'
            candidate.write_bytes(b'new verified output');output.write_bytes(b'original user file')
            def failed_commit():raise OSError('disk full while committing manifest')
            with self.assertRaises(OSError):publish(candidate,output,True,failed_commit,[])
            self.assertEqual(output.read_bytes(),b'original user file')
            self.assertEqual(list(root.glob('*.pending')),[])
            self.assertEqual(list(root.glob('*.vaani-backup-*')),[])
    def test_late_manifest_failure_removes_new_uncommitted_output(self):
        from vaani.publication import publish
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'candidate.wav';output=root/'new.wav'
            candidate.write_bytes(b'new verified output')
            def failed_commit():raise OSError('disk full')
            with self.assertRaises(OSError):publish(candidate,output,False,failed_commit,[])
            self.assertFalse(output.exists())

if __name__=='__main__':unittest.main()
