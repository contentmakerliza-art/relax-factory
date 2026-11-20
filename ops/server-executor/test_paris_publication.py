import hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('publisher',Path(__file__).with_name('publish-approved-card.py'))
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class ParisPublicationTests(unittest.TestCase):
    def exercise(self,approval='одобрено',bad_track=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);job_id='20261120-193143-4575';folder=root/job_id
            (folder/'visual').mkdir(parents=True);(folder/'tracks').mkdir()
            content=b'exact reviewed preview';digest=hashlib.sha256(content).hexdigest()
            (folder/'preview.mp4').write_bytes(content)
            (folder/'visual/approved-master.mp4').write_bytes(content)
            (folder/'job.json').write_text(json.dumps(dict(approval={'status':approval},
                status='готово',output='preview.mp4',settings={})))
            tracks=[]
            for i in range(6):
                p=folder/'tracks'/f'{i}.mp3';p.write_bytes(bytes([i])*100)
                tracks.append(dict(name=p.name,seconds=120,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            if bad_track:(folder/'tracks/0.mp3').write_bytes(b'changed')
            manifest=dict(job_id=job_id,profile='Little_Paris_Jazz_Cafe',channel='Little Paris Jazz Cafe',
                recipe_verified=True,preview_sha256=digest,full_tracks=tracks,publish_at='2026-12-16T22:00',
                title='Snowy Bologna Cafe | Cozy Winter Jazz | 3 Hours',description='Winter jazz',tags='jazz')
            (root/('codex-manifest-'+job_id+'.json')).write_text(json.dumps(manifest))
            calls=[]
            def call(path,method='GET',values=None,file=None):
                calls.append((path,method))
                if path=='/queue':return [] if method=='GET' else {'id':'new','status':'ждёт'}
                self.fail('Unexpected service call '+path)
            def path(value):
                p=Path(value)
                if p==Path('/tmp'):return root
                return root/p.name if p.parent==Path('/tmp') else p
            with patch.dict(os.environ,{'APP_DATA':str(root)}),patch.object(publisher,'Path',side_effect=path),\
                 patch.object(publisher.runpy,'run_path',return_value={'call':call}):
                if approval!='одобрено' or bad_track:
                    with self.assertRaises(ValueError):publisher.main(job_id)
                    self.assertNotIn(('/queue','POST'),calls)
                else:
                    publisher.main(job_id)
                    self.assertEqual(calls,[('/queue','GET'),('/queue','POST')])
                    settings=json.loads((folder/'job.json').read_text())['settings']
                    self.assertEqual((settings['width'],settings['fps'],settings['loop_mode']),(1920,24,'chain'))

    def test_exact_approved_paris_uses_full_music_not_fireplace(self):self.exercise()
    def test_waiting_preview_cannot_publish(self):self.exercise(approval='ждёт')
    def test_changed_full_track_cannot_publish(self):self.exercise(bad_track=True)
