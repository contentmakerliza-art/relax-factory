import copy,json,tempfile,unittest,hashlib,sqlite3,os
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import window_snow_contract as c
import window_snow_auto as worker
import cabin_backlog_registry as registry


def plan():
 return {'verdict':'READY','glass':[{'label':'pane','polygon':[[100,100],[600,100],[600,600],[100,600]]}],
 'foreground':[{'label':'complete wooden chair back','polygon':[[320,300],[440,300],[440,520],[320,520]]}],
 'inset_fullhd_px':4,'rigid_regions':[[60,40,60,60],[650,40,60,60],[650,600,60,60]],'notes':'safe'}

class ContractTests(unittest.TestCase):
 def test_snow_excludes_full_chair_back_and_notch(self):
  mask=c.make_mask(plan())
  self.assertIsNone(mask.crop((320,300,441,521)).getbbox())
  self.assertEqual(mask.getpixel((102,200)),0)
  self.assertGreater(mask.getpixel((200,200)),250)
 def test_unsafe_coordinates_and_small_inset_are_rejected(self):
  for mutation in [lambda p:p.update(inset_fullhd_px=1),lambda p:p['glass'][0]['polygon'][0].__setitem__(0,1280),lambda p:p.update(verdict='UNCERTAIN')]:
   value=plan();mutation(value)
   with self.assertRaises(ValueError):c.validate_plan(value)
 def test_crossing_glass_polygon_is_not_rasterized(self):
  value=plan();value['glass'][0]['polygon']=[[100,100],[500,500],[100,500],[500,100],[600,100]]
  with self.assertRaises(ValueError):c.validate_plan(value)
 def test_border_measurement_is_dropped_without_altering_glass(self):
  value=plan();original=copy.deepcopy(value['glass']);value['rigid_regions'].append([1243,339,29,146])
  kept=c.retained_rigid_regions(value)
  self.assertEqual(len(kept),3);self.assertEqual(value['glass'],original)
 def test_job_identity_changes_for_new_source_or_owner_decision(self):
  a=c.job_id('cabin05-fixed-v15-20261121','a'*64)
  self.assertEqual(a,c.job_id('cabin05-fixed-v15-20261121','a'*64))
  self.assertNotEqual(a,c.job_id('cabin05-fixed-v15-20261121','a'*64,'decision2'))
  self.assertNotEqual(a,c.job_id('cabin05-fixed-v15-20261121','b'*64))
  with self.assertRaises(ValueError):c.job_id('exhale-22','a'*64)
 def test_dynamic_registry_preserves_room_and_parent_allowlist(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rid='cabin05-auto-0123456789abcdef-a1';p=root/'window-snow/requests'/(rid+'.json');p.parent.mkdir(parents=True)
   p.write_text(json.dumps({'request_id':rid,'parent_request_id':'cabin05-fixed-v15-20261121','group':'g'}))
   rows=[{'request_group':'g','sources':[{'attempts':['cabin05-fullframe-v15-20261121']}]}]
   with patch.object(registry,'ROOT',root),patch.object(registry,'records',return_value=rows):
    self.assertTrue(registry.attempt(rid,'g'));self.assertFalse(registry.attempt(rid,'other'))
    p.write_text(json.dumps({'request_id':rid,'parent_request_id':'cabin20-fixed-v15-20261121','group':'g'}))
    with self.assertRaises(ValueError):registry.attempt(rid,'g')
 def test_empty_or_terminal_queue_uses_no_ai_or_media(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   with patch.object(worker,'STATE',root),patch.object(worker,'process') as process:
    worker.main();process.assert_not_called()
    folder=root/'jobs'/'finished';folder.mkdir(parents=True)
    worker.atomic(folder/'request.json',{'id':'finished'});worker.atomic(folder/'state.json',{'stage':'delivered'})
    worker.main();process.assert_not_called()
 def test_telegram_snow_feedback_routes_exact_decision_to_worker(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'data';data.mkdir();rid='cabin05-snow-v15-20261121';job='20261121-120000-abcd';parent='cabin05-fixed-v15-20261121'
   worker.atomic(data/('codex-delivery-'+rid+'.json'),{'job_id':job})
   worker.atomic(root/'assets'/rid/'recipe-and-checks.json',{'parent_request_id':parent})
   worker.atomic(root/'assets'/parent/'visual-qc.json',{'verdict':'NEEDS_MOTION_REVIEW'})
   row={'job_id':job,'label':'Quiet Pines Cabin — test','status':'правка','time':1,'comments':[{'text':'Снег на спинке стула'}],'archived':False}
   identity=hashlib.sha256(json.dumps({k:row[k] for k in ['job_id','status','time','comments']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
   db=sqlite3.connect(':memory:');db.execute('CREATE TABLE tasks(id TEXT,state TEXT)');db.execute('INSERT INTO tasks VALUES (?,?)',(identity,'pending_executor'))
   with patch.object(worker,'ROOT',root),patch.object(worker,'DATA',data),patch.object(worker,'enqueue',return_value='queued') as enqueue:
    self.assertTrue(worker.dispatch_decision(identity,row,db));enqueue.assert_called_once()
    self.assertEqual(db.execute('SELECT state FROM tasks').fetchone()[0],'window_queued')
    with self.assertRaises(ValueError):worker.dispatch_decision('a'*64,row,db)
 def test_fresh_layout_records_start_before_model_and_reuses_result(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);prepared=root/'prepared';prepared.mkdir();(root/'workspace').mkdir()
   for i in range(4):(prepared/f'frame{i}.png').write_bytes(b'frame')
   cache=root/'cache';job={'id':'cabin20-auto-0123456789abcdef'}
   real_path=Path
   def mapped(value):return root/'workspace' if str(value)=='/var/lib/relax-codex/workspace' else real_path(value)
   calls=[]
   def execute(args,**kwargs):
    self.assertTrue((cache/'model-started.json').exists());calls.append(args)
    real_path(args[args.index('-o')+1]).write_text(json.dumps(plan()))
   with patch.object(worker,'Path',side_effect=mapped),patch.object(worker.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())),patch.object(worker.os,'chown'),patch.object(worker,'run',side_effect=execute):
    first=worker.codex_layout(prepared,job,1,'',cache)
    second=worker.codex_layout(prepared,job,1,'',cache)
   self.assertEqual(first,second);self.assertEqual(len(calls),1)
 def test_enqueue_is_durable_and_deduplicated(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);parent='cabin05-fixed-v15-20261121';p=root/'assets'/parent;p.mkdir(parents=True)
   (p/'normalized.mp4').write_bytes(b'exact-source');worker.atomic(p/'visual-qc.json',{'verdict':'NEEDS_MOTION_REVIEW'})
   row=({'request_group':'g'},0)
   with patch.object(worker,'ROOT',root),patch.object(worker,'STATE',root/'window-snow'),patch.object(registry,'entry',return_value=row):
    first=worker.enqueue(parent,kick=False);raw=(root/'window-snow/jobs'/first/'request.json').read_bytes()
    again=worker.enqueue(parent,kick=False)
    self.assertEqual(first,again);self.assertEqual(raw,(root/'window-snow/jobs'/first/'request.json').read_bytes())
    self.assertEqual(len(list((root/'window-snow/jobs').glob('*/request.json'))),1)

if __name__=='__main__':unittest.main()
