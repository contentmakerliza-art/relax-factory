import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retry', Path(__file__).with_name('production-retry.py'))
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class ProductionRetryTests(unittest.TestCase):
    def setup_files(self, root):
        retry.ROOT = root / 'executor'
        retry.DOWNLOADS = root / 'downloads'
        retry.STATE = root / 'state'
        for p in (retry.ROOT, retry.DOWNLOADS, retry.STATE): p.mkdir()
        (retry.DOWNLOADS / 'original.jpg').write_bytes(b'original' * 2000)
        config = {'channel': 'Quiet Pines Cabin', 'request_group': 'cabin08-retry-20261120', 'sources': [
            {'file': '/downloads/original.jpg', 'runway_prompt': 'still room',
             'attempts': [f'cabin08-fullframe-v{i}-20261120' for i in (1, 2, 3)]},
            {'new_image_request': str(retry.DOWNLOADS / 'new.json'), 'runway_prompt': 'new still room',
             'attempts': [f'cabin08-fullframe-v{i}-20261120' for i in (4, 5, 6)]}]}
        (retry.DOWNLOADS / 'new.json').write_text(json.dumps({'request_id': 'cabin08-source-new-v1-20261120'}))
        path = root / 'config.json'; path.write_text(json.dumps(config))
        return config, path

    def test_three_rejections_change_image_and_good_attempt_stops_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, path = self.setup_files(Path(tmp))
            for rid in config['sources'][0]['attempts']:
                p = retry.ROOT / 'assets' / rid; p.mkdir(parents=True)
                (p / 'pipeline.json').write_text(json.dumps({'stage': 'rejected'}))
            calls = []
            def fake(args, **kw):
                calls.append(args)
                if '/app/banana-edit-cabin.py' in args:
                    (retry.DOWNLOADS / 'new.jpg').write_bytes(b'new room' * 2000)
                    (retry.STATE / 'cabin08-source-new-v1-20261120.json').write_text(json.dumps({
                        'state': 'downloaded_needs_qc', 'file': '/downloads/new.jpg'}))
                elif str(retry.ROOT / 'source-review.py') in args:
                    return type('Result', (), {'stdout': json.dumps({'verdict': 'NEEDS_VIDEO_TEST'})})()
                elif '/app/runway_prepare.py' in args:
                    q=json.loads((retry.DOWNLOADS / Path(args[args.index('--request') + 1]).name).read_text())
                    (retry.STATE / ('runway-' + q['request_id'] + '.json')).write_text(json.dumps({'state':'downloaded_needs_qc'}))
                elif str(retry.ROOT / 'pipeline-one.py') in args:
                    rid=args[-1];p=retry.ROOT / 'assets' / rid
                    outcome={'stage':'rejected'} if '-v4-' in rid else {'stage':'held_for_motion_and_audio_review','preview':'checked.mp4'}
                    (p / 'pipeline.json').write_text(json.dumps(outcome))
                return type('Result', (), {'stdout': '{}'})()
            with patch.object(retry, 'run', side_effect=fake):
                retry.main(path)
                retry.main(path)
            generations=[x for x in calls if '/app/runway_prepare.py' in x]
            self.assertEqual(len(generations), 2)
            state=json.loads((retry.ROOT/'production-runs/cabin08-retry-20261120/state.json').read_text())
            self.assertEqual(state['stage'], 'preview_ready_for_final_checks')
            self.assertIn('-v5-', state['request_id'])

    def test_uncertain_submission_never_generates_or_buys_new_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            rid=config['sources'][0]['attempts'][0]
            (retry.STATE/('runway-'+rid+'.json')).write_text(json.dumps({'state':'submission_uncertain'}))
            with patch.object(retry,'run') as run:
                retry.main(path)
                run.assert_not_called()
            state=json.loads((retry.ROOT/'production-runs/cabin08-retry-20261120/state.json').read_text())
            self.assertEqual(state['stage'],'recover_existing_video')


if __name__=='__main__':unittest.main()
