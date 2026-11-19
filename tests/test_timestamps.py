"""Contracts for optional analysis, recovery, pair publication and private configuration."""
import json,math,struct,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
from vaani.api import synthesize
from vaani.cli import build_parser
from vaani.config import save,sha,whisper_settings
from vaani.types import SynthesisRequest,VaaniError
from vaani.timestamps import validate_packet,SCHEMA,preflight


def fixture(root):
    (root/'config').mkdir();(root/'.runtime/envs/chatterbox/bin').mkdir(parents=True);(root/'.runtime/envs/chatterbox/bin/python').touch()
    save(root/'config/voices.json',{'voices':{'amit':{'backend':'chatterbox','default_seed':42,'assets':[],'settings':{},'profile_version':'test'}}})


def speech(root,profile,tasks,job,request,progress,started):
    for task in tasks:
        p=Path(task['file']);p.parent.mkdir(parents=True,exist_ok=True)
        pcm=b''.join(struct.pack('<h',int(4000*math.sin(2*math.pi*180*i/24000)))for i in range(24000))
        with wave.open(str(p),'wb')as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
        save(p.with_suffix('.json'),{'cache_key':task['cache_key'],'sha256':sha(p)})
    return {'status':'complete'}


def timings(root,audio,name,intervals,job,request,progress,started):
    out=job/'word-timestamps.json'
    save(out,{'schema_version':SCHEMA,'analysis_key':'test','audio':{'filename':name,'sha256':sha(audio),'duration_seconds':1.0},'text':'Hello','segments':[{'words':[{'word':'Hello','start':.1,'end':.8,'probability':.9}]}]})
    return out,False


class TimestampContracts(unittest.TestCase):
    def test_cli_flag_is_opt_in_and_can_explicitly_disable_on_resume(self):
        parser=build_parser();base=['synthesize','--input','speech.txt','--output','speech.wav']
        self.assertIsNone(parser.parse_args(base).word_timestamps)
        self.assertTrue(parser.parse_args(base+['--word-timestamps']).word_timestamps)
        self.assertFalse(parser.parse_args(base+['--no-word-timestamps']).word_timestamps)

    def test_local_override_uses_existing_config_structure_without_changing_voice(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root)
            shared=(root/'config/voices.json').read_bytes()
            save(root/'config/voices.local.json',{'whisper':{'model_path':'../downloaded-model','language':'auto'}})
            settings=whisper_settings(root)
            self.assertEqual(settings['model_path'],(root/'../downloaded-model').resolve());self.assertIsNone(settings['language'])
            self.assertEqual((root/'config/voices.json').read_bytes(),shared)
            save(root/'config/voices.local.json',{'whisper':{'model_path':False}})
            with self.assertRaises(VaaniError):whisper_settings(root)

    def test_default_synthesis_never_calls_analysis(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root)
            with patch('vaani.api.fingerprint',return_value='test'),patch('vaani.api._run_worker',side_effect=speech),patch('vaani.timestamps.preflight')as pre,patch('vaani.timestamps.run_timestamps')as run:
                result=synthesize(SynthesisRequest(root/'out.wav',text='Hello there.'),root=root)
            pre.assert_not_called();run.assert_not_called();self.assertNotIn('timestamps_file',result.to_dict())

    def test_opt_in_sidecar_matches_audio_and_runs_after_speech(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root);order=[]
            def say(*args):order.append('speech');return speech(*args)
            def analyze(*args):self.assertEqual(order,['speech']);order.append('timestamps');return timings(*args)
            with patch('vaani.api.fingerprint',return_value='test'),patch('vaani.api._run_worker',side_effect=say),patch('vaani.timestamps.preflight'),patch('vaani.timestamps.run_timestamps',side_effect=analyze):
                result=synthesize(SynthesisRequest(root/'out.wav',text='Hello there.',word_timestamps=True),root=root)
            self.assertEqual(order,['speech','timestamps']);self.assertEqual(result.timestamps_file,(root/'out.timestamps.json').resolve())
            packet=json.loads(result.timestamps_file.read_text());self.assertEqual(packet['audio']['sha256'],sha(result.output_file))
            self.assertNotIn(str(root),result.timestamps_file.read_text())

    def test_timestamp_failure_keeps_speech_recoverable_and_resume_retains_option(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root)
            with patch('vaani.api.fingerprint',return_value='test'),patch('vaani.api._run_worker',side_effect=speech)as say,patch('vaani.timestamps.preflight'),patch('vaani.timestamps.run_timestamps',side_effect=VaaniError(8,'Timing failed')):
                with self.assertRaises(VaaniError)as caught:synthesize(SynthesisRequest(root/'out.wav',text='Hello there.',word_timestamps=True),root=root)
            job=Path(caught.exception.job_directory);self.assertTrue(Path(caught.exception.details['audio_file']).is_file());self.assertFalse((root/'out.wav').exists())
            with patch('vaani.api.fingerprint',return_value='test'),patch('vaani.api._run_worker',side_effect=AssertionError('Speech must be reused')),patch('vaani.timestamps.preflight'),patch('vaani.timestamps.run_timestamps',side_effect=timings):
                result=synthesize(SynthesisRequest(root/'out.wav',resume_job_dir=job),root=root)
            self.assertTrue(result.cache_reused);self.assertTrue(result.timestamps_file.is_file())

    def test_late_manifest_failure_restores_both_previous_outputs(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root);audio=root/'out.wav';sidecar=root/'out.timestamps.json';audio.write_bytes(b'old audio');sidecar.write_bytes(b'old timestamps')
            from vaani import api
            actual_save=api.save
            def commit_failure(path,data):
                if data.get('status')=='complete':raise OSError('manifest commit failure')
                return actual_save(path,data)
            with patch('vaani.api.fingerprint',return_value='test'),patch('vaani.api._run_worker',side_effect=speech),patch('vaani.timestamps.preflight'),patch('vaani.timestamps.run_timestamps',side_effect=timings),patch('vaani.api.save',side_effect=commit_failure):
                with self.assertRaises(VaaniError):synthesize(SynthesisRequest(audio,text='Hello there.',word_timestamps=True,overwrite=True),root=root)
            self.assertEqual(audio.read_bytes(),b'old audio');self.assertEqual(sidecar.read_bytes(),b'old timestamps')

    def test_existing_sidecar_is_protected_before_any_speech(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root);(root/'out.timestamps.json').write_text('user file')
            with patch('vaani.api._run_worker')as say:
                with self.assertRaises(VaaniError)as caught:synthesize(SynthesisRequest(root/'out.wav',text='Hello there.',word_timestamps=True),root=root)
            self.assertEqual(caught.exception.code,9);say.assert_not_called()

    def test_packet_rejects_stale_audio_and_impossible_word_boundaries(self):
        packet={'schema_version':SCHEMA,'analysis_key':'key','audio':{'sha256':'hash','duration_seconds':1},'text':'Hello','segments':[{'words':[{'word':'Hello','start':.1,'end':.8,'probability':.9}]}]}
        self.assertEqual(validate_packet(packet,'hash','key',1),1)
        with self.assertRaises(ValueError):validate_packet(packet,'changed','key',1)
        packet['segments'][0]['words'][0]['end']=2
        with self.assertRaises(ValueError):validate_packet(packet,'hash','key',1)
        packet['segments'][0]['words'][0]['end']=float('nan')
        with self.assertRaises(ValueError):validate_packet(packet,'hash','key',1)

    def test_missing_whisper_is_rejected_before_speech(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);fixture(root)
            with patch('vaani.api._run_worker')as say:
                with self.assertRaises(VaaniError)as caught:synthesize(SynthesisRequest(root/'out.wav',text='Hello there.',word_timestamps=True),root=root)
            self.assertEqual(caught.exception.code,4);say.assert_not_called()

if __name__=='__main__':unittest.main()
