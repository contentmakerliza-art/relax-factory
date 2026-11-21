"""Restart regressions: durable rejections never rerun model/render work."""
import importlib.util,json,tempfile,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).parent/'cabin-backlog'
def load(name):
 spec=importlib.util.spec_from_file_location(name,BASE/(name+'.py'))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
producer=load('production-retry');finisher=load('finish-production')
def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
class NoRepeatTests(unittest.TestCase):
 def test_next_submission_uses_specific_previous_defect(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);downloads=root/'downloads';downloads.mkdir();(downloads/'source.jpg').write_bytes(b'source')
   folder=root/'run';folder.mkdir();state=root/'state';state.mkdir()
   ids=['cabin05-fullframe-v1-20261121','cabin05-fullframe-v2-20261121']
   write(state/('runway-'+ids[0]+'.json'),{'state':'downloaded_needs_qc'})
   write(root/'assets'/ids[0]/'pipeline.json',{'stage':'rejected_preview','defects':['Нет заметного снегопада за окном']})
   write(root/'assets'/ids[0]/'long-segment.json',{'state':'no_clean_eight_second_segment'})
   config={'request_group':'cabin05-backlog-20261121','sources':[{'file':'/downloads/source.jpg','runway_prompt':'Fixed scene base','attempts':ids}]}
   submissions=[]
   def execute(args,**kw):
    if args[1].endswith('await-syntx.py'):
     req=json.loads(Path(args[3]).read_text());submissions.append(req)
     self.assertIn('Dense, abundant snowfall',req['prompt'])
     write(state/('runway-'+ids[1]+'.json'),{'state':'downloaded_needs_qc'})
    elif args[1].endswith('pipeline-one.py'):
     write(root/'assets'/ids[1]/'pipeline.json',{'stage':'held_for_motion_and_audio_review','preview':'checked.mp4'})
    else:self.fail('Unexpected expensive operation: '+str(args))
   with patch.object(producer,'ROOT',root),patch.object(producer,'DOWNLOADS',downloads),patch.object(producer,'STATE',state),patch.object(producer,'media_slot',side_effect=nullcontext),patch.object(producer.backlog,'prepare_geometry'),patch.object(producer,'run',side_effect=execute):
    producer.work(config,folder);producer.work(config,folder)
   self.assertEqual(len(submissions),1)
   audit=json.loads(next((folder/'corrections').glob('*.json')).read_text())
   self.assertEqual(audit['evidence'][0]['request_id'],ids[0])
 def test_restart_and_policy_change_skip_rejected_media_and_cached_trim(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);downloads=root/'downloads';downloads.mkdir();(downloads/'source.jpg').write_bytes(b'source')
   folder=root/'run';folder.mkdir();state=root/'state';state.mkdir()
   ids=['cabin05-fullframe-v1-20261121','cabin05-fullframe-v2-20261121']
   for rid in ids:write(state/('runway-'+rid+'.json'),{'state':'downloaded_needs_qc'})
   write(root/'assets'/ids[0]/'pipeline.json',{'stage':'rejected_preview','motion_policy_version':'old-policy','defects':['snow indoors']})
   write(root/'assets'/ids[0]/'long-segment.json',{'state':'no_clean_eight_second_segment','motion_policy_version':'old-policy'})
   write(root/'assets'/ids[1]/'pipeline.json',{'stage':'held_for_motion_and_audio_review','preview':'checked-preview.mp4'})
   config={'request_group':'cabin05-backlog-20261121','sources':[{'file':'/downloads/source.jpg','attempts':ids}]}
   with patch.object(producer,'ROOT',root),patch.object(producer,'DOWNLOADS',downloads),patch.object(producer,'STATE',state),patch.object(producer,'media_slot',side_effect=nullcontext),patch.object(producer.backlog,'prepare_geometry'),patch.object(producer,'run') as expensive:
    producer.work(config,folder);producer.work(config,folder)
    expensive.assert_not_called()
   self.assertEqual(json.loads((folder/'state.json').read_text())['request_id'],ids[1])
   self.assertEqual(json.loads((root/'assets'/ids[0]/'pipeline.json').read_text())['stage'],'rejected_preview')
 def test_finisher_returns_immediately_for_known_rejection_after_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'run';folder.mkdir();rid='cabin05-fullframe-v1-20261121';group='cabin05-backlog-20261121'
   write(folder/'delivery.json',{'stage':'deferred_after_preview_rejection','motion_policy_version':'old-policy','rejected_requests':[rid]})
   write(folder/'state.json',{'stage':'preview_ready_for_final_checks','request_id':rid})
   write(root/'production-configs'/(group+'.json'),{})
   write(root/'assets'/rid/'pipeline.json',{'stage':'rejected_preview','defects':['snow indoors']})
   with patch.object(finisher,'ROOT',root),patch.object(finisher,'run') as expensive,patch.object(finisher.time,'sleep') as wait:
    finisher.finish(group,folder);finisher.finish(group,folder)
    expensive.assert_not_called();wait.assert_not_called()
   result=json.loads((folder/'delivery.json').read_text())
   self.assertEqual(result['stage'],'deferred_after_preview_rejection');self.assertEqual(result['defects'],['snow indoors'])
if __name__=='__main__':unittest.main()
