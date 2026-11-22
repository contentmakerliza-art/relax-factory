import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


class Corrections(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        stub=types.ModuleType('mountain_batch');stub.ROOT=root;stub.DATA=root;stub.BATCH=root
        stub.read=lambda p,default=None:json.loads(p.read_text()) if p.exists() else default
        stub.save=lambda p,v:p.write_text(json.dumps(v))
        sys.modules['mountain_batch']=stub
        contract=types.ModuleType('window_snow_contract');contract.schema=lambda:{};contract.validate_plan=lambda x:x
        sys.modules['window_snow_contract']=contract
        spec=importlib.util.spec_from_file_location('corrections',Path(__file__).with_name('mountain_corrections.py'))
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m);self.calls=[]
        self.m.update_task=lambda *x:self.calls.append(x)

    def row(self):
        return dict(job_id='job',label='Mountain View Cafe — test',status='правка',time=1,comments=[{'text':'Снег почти не виден','time':2}],archived=False)

    def test_scope_and_owner_decision(self):
        row=self.row();self.assertTrue(self.m.supported(row))
        for change in ({'status':'одобрено'},{'label':'Little Paris Jazz Cafe'},{'archived':True},{'comments':[]}):
            self.assertFalse(self.m.supported(dict(row,**change)))

    def test_new_comment_supersedes_old_work(self):
        row=self.row();p=self.m.b.DATA/'job';p.mkdir()
        (p/'job.json').write_text(json.dumps({'approval':{k:row[k] for k in ('status','time','comments')}}))
        key=self.m.fingerprint(row);self.assertTrue(self.m.current(key,'job'))
        row['comments'].append({'text':'Новая правка','time':3})
        (p/'job.json').write_text(json.dumps({'approval':{k:row[k] for k in ('status','time','comments')}}))
        self.assertFalse(self.m.current(key,'job'))

    def test_requested_is_not_delivered_and_restart_is_idempotent(self):
        folder=self.m.b.DATA/'fix';folder.mkdir();(folder/'config.json').write_text(json.dumps({'request_id':'fix'}))
        (self.m.b.DATA/'mountain-delivery-fix.json').write_text(json.dumps({'job_id':'new','stage':'telegram_requested'}))
        new=self.m.b.DATA/'new';new.mkdir();meta=new/'job.json'
        meta.write_text(json.dumps({'telegram':{'status':'ожидает'}}))
        self.assertTrue(self.m.reconcile_delivery(folder,'task'));self.assertFalse(self.calls)
        meta.write_text(json.dumps({'telegram':{'status':'отправлено'}}))
        self.assertTrue(self.m.reconcile_delivery(folder,'task'))
        self.assertEqual(self.calls[-1],('task','mountain_correction_delivered'))
        self.assertTrue(self.m.reconcile_delivery(folder,'task'))
        self.assertEqual(json.loads((folder/'state.json').read_text())['job_id'],'new')

    def test_partial_delivery_never_creates_second_job(self):
        folder=self.m.b.DATA/'fix';folder.mkdir();(folder/'config.json').write_text(json.dumps({'request_id':'fix'}))
        (self.m.b.DATA/'mountain-delivery-fix.json').write_text(json.dumps({'stage':'creating_job_uncertain'}))
        with self.assertRaisesRegex(RuntimeError,'no duplicate'):self.m.reconcile_if_present(folder,'task')


if __name__=='__main__':unittest.main()
