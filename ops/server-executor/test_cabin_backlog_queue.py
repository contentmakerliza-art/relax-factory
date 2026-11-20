"""Regression: planning may enqueue synchronously; never post the source twice."""
import contextlib,importlib.util,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('backlog',Path(__file__).with_name('queue-approved-cabin-backlog.py'))
backlog=importlib.util.module_from_spec(spec);spec.loader.exec_module(backlog)

class CabinBacklogTests(unittest.TestCase):
    def test_plan_callback_queues_once_without_explicit_second_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);jid='20261119-203840-ac20';folder=root/jid
            (folder/'visual').mkdir(parents=True);(folder/'mask').mkdir()
            (folder/'approved.mp4').write_bytes(b'approved video')
            (folder/'visual/approved-master.mp4').write_bytes(b'approved video')
            meta=dict(approval={'status':'одобрено'},status='готово',
                      label='Quiet Pines Cabin — 04 декабря — artist',output='approved.mp4',
                      settings=dict(loop_mode='chain',loop_crossfade=0,stabilize=False,speed=1))
            (folder/'job.json').write_text(json.dumps(meta))
            queue=[];calls=[]
            def call(path,method='GET',values=None,*args):
                calls.append((path,method))
                if path=='/queue':
                    self.assertEqual(method,'GET','Must not create another queue item')
                    return list(queue)
                if path.endswith('/background-audio'):
                    return dict(sha256='5da945ef4e6ba128fe3c2241afd8725d2b366e8a49b4831a7776356310235b5f',seconds=109)
                if path=='/production/'+jid+'/plan':
                    queue.append(dict(id='automatic',source=jid,status='ждёт',publish_at=values['publish_at']))
                    return {}
                self.fail('Unexpected API write: '+path)
            with patch.object(backlog,'DATA',root),patch.object(backlog,'ROWS',[(jid,'04','Artist Cabin')]),\
                 patch.object(backlog.runpy,'run_path',return_value={'call':call}),contextlib.redirect_stdout(io.StringIO()):
                backlog.main()
                backlog.main()
            self.assertEqual(len(queue),1)
            self.assertEqual(sum(path.startswith('/production/') for path,method in calls),1)
            self.assertEqual(json.loads((folder/'job.json').read_text()),meta)
            receipt=json.loads((folder/'backlog-publication-receipt.json').read_text())
            self.assertEqual(receipt['publication']['id'],'automatic')

if __name__=='__main__':unittest.main()
