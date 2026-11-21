"""A guided Exhale source must not be rejected for lacking a visual loop."""
import importlib.util,json,sys,tempfile,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('exhale_approval_queue',Path(__file__).parents[2]/'approval_queue.py')
with patch.dict(sys.modules,{'fastapi':SimpleNamespace(Depends=lambda x:x,Form=lambda *a,**k:None,HTTPException=RuntimeError)}):
    approval_queue=importlib.util.module_from_spec(spec);spec.loader.exec_module(approval_queue)

class ExhaleQueueSourcesTests(unittest.TestCase):
    def run_source(self,breath):
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory);jid='20261119-102030-80a8';folder=data/jid
            (folder/'voice').mkdir(parents=True);(folder/'ambient').mkdir()
            (folder/'voice/00-voice.wav').write_bytes(b'complete preserved voice')
            (folder/'ambient/background.flac').write_bytes(b'complete preserved background')
            if breath:(folder/'breath.json').write_text(json.dumps(dict(script='preserved script')))
            row=dict(source=jid,label='Exhale to Sleep',channel='Exhale to Sleep',publish_at='2026-11-30T22:00',
                title='Guided breathing',description='',tags='',profile='Exhale_to_Sleep',hours=10,
                approval_time=1,created='',history=[],status='',blocker='')
            (data/'approved-production-queue.json').write_text(json.dumps({jid:row}))
            publications=[];queued=[]
            def ready(record):
                queued.append(record['source'])
                value=dict(source=jid,id='automatic',status='ждёт',publish_at=record['publish_at'],
                    channel='Exhale to Sleep',user='Exhale_to_Sleep',hours=10)
                publications.append(value);return value
            q=approval_queue.ApprovalQueue(data,{jid:dict(approval={'status':'одобрено','time':1})},publications,
                lambda source,kind:folder/kind if kind=='ambient' else None,
                lambda info:'Exhale to Sleep',lambda:datetime(2026,11,21),ready)
            result=q.sync()[0];q.sync()
            return queued,result

    def test_complete_voice_recipe_queues_without_a_visual_loop(self):
        queued,result=self.run_source(True)
        self.assertEqual(len(queued),1)
        self.assertEqual(result['status'],'Очередь публикаций: ждёт')

    def test_voice_without_breathing_recipe_stays_blocked(self):
        queued,result=self.run_source(False)
        self.assertEqual(queued,[])
        self.assertIn('нет исходного клипа',result['blocker'])

if __name__=='__main__':unittest.main()
