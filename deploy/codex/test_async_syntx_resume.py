import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('await_syntx',Path(__file__).parent/'cabin-backlog/await-syntx.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
class AsyncResumeTests(unittest.TestCase):
    def case(self,root,state):
        worker.ROOT=root;worker.STATE=root/'state';worker.STATE.mkdir()
        request=root/'cabin05-fullframe-v1-20261121-request.json';rid='cabin05-fullframe-v1-20261121'
        request.write_text(json.dumps({'request_id':rid}))
        ledger=worker.STATE/('runway-'+rid+'.json')
        if state:ledger.write_text(json.dumps(state))
        return request,ledger
    def test_downloaded_result_never_submits_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,ledger=self.case(Path(tmp),{'state':'downloaded_needs_qc'})
            with patch.object(worker,'run') as call:worker.main('video',request);call.assert_not_called()
    def test_existing_submission_only_polls(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,ledger=self.case(Path(tmp),{'state':'submitted','async_submission':True})
            def poll(script,args):
                self.assertEqual(script,'async-syntx-poll.py');ledger.write_text(json.dumps({'state':'downloaded_needs_qc'}));return {}
            with patch.object(worker,'run',side_effect=poll),patch.object(worker.time,'sleep'):worker.main('video',request)
    def test_uncertain_submission_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,ledger=self.case(Path(tmp),{'state':'submission_uncertain'})
            with patch.object(worker,'run') as call:
                with self.assertRaises(RuntimeError):worker.main('video',request)
                call.assert_not_called()
    def test_new_submission_is_reserved_once_then_polled(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,ledger=self.case(Path(tmp),None);calls=[]
            def run(script,args):
                calls.append(script);ledger.write_text(json.dumps({'state':'submitted','async_submission':True} if len(calls)==1 else {'state':'downloaded_needs_qc'}));return {}
            with patch.object(worker,'run',side_effect=run),patch.object(worker.time,'sleep'):worker.main('video',request)
            self.assertEqual(calls,['async-runway-submit.py','async-syntx-poll.py'])
if __name__=='__main__':unittest.main()
