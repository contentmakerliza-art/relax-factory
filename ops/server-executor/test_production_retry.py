import importlib.util
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retry', Path(__file__).with_name('production-retry.py'))
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class ProductionRetryTests(unittest.TestCase):
    def test_extra_technical_slots_never_allow_more_than_three_bad_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            config['sources']=config['sources'][:1]
            config['sources'][0]['attempts']=[f'cabin08-fullframe-v{i}-20261120' for i in range(1,7)]
            path.write_text(json.dumps(config))
            calls=[]
            def fake(args,**kwargs):
                if '/app/runway_prepare.py' in args:
                    q=json.loads((retry.DOWNLOADS/Path(args[args.index('--request')+1]).name).read_text())
                    calls.append(q['request_id'])
                    (retry.STATE/('runway-'+q['request_id']+'.json')).write_text(json.dumps({
                        'state':'downloaded_needs_qc','model':q['model'],'created':len(calls)}))
                elif str(retry.ROOT/'pipeline-one.py') in args:
                    (retry.ROOT/'assets'/args[-1]/'pipeline.json').write_text(json.dumps({'stage':'rejected'}))
                elif str(retry.ROOT/'try-long-segment.py') in args:
                    return type('Result',(),{'stdout':json.dumps({'state':'no_clean_eight_second_segment'})})()
                else:self.fail(str(args))
                return type('Result',(),{'stdout':'{}'})()
            with patch.object(retry,'run',side_effect=fake):retry.main(path)
            self.assertEqual(len(calls),3)

    def test_two_technical_failures_stop_model_before_third_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            calls=[]
            def fake(args,**kwargs):
                self.assertIn('/app/runway_prepare.py',args)
                q=json.loads((retry.DOWNLOADS/Path(args[args.index('--request')+1]).name).read_text())
                self.assertEqual(q['model'],'Gen-4 Turbo')
                calls.append(q)
                (retry.STATE/('runway-'+q['request_id']+'.json')).write_text(json.dumps({
                    'state':'generation_failed','model':q['model'],'created':len(calls)}))
                return type('Result',(),{'stdout':'{}'})()
            with patch.object(retry,'run',side_effect=fake):retry.main(path)
            state=json.loads((retry.ROOT/'production-runs/cabin08-retry-20261120/state.json').read_text())
            self.assertEqual(len(calls),2)
            self.assertEqual(state['stage'],'model_unavailable_no_retry')
            self.assertEqual(state['completed_video_attempts'],0)

    def test_technical_failure_is_not_third_bad_video_and_buys_no_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            for i,rid in enumerate(config['sources'][0]['attempts']):
                if i == 1:
                    (retry.STATE/('runway-'+rid+'.json')).write_text(json.dumps({
                        'state':'generation_failed','model':'Gen-4 Turbo','created':1}))
                else:
                    p=retry.ROOT/'assets'/rid;p.mkdir(parents=True)
                    (p/'pipeline.json').write_text(json.dumps({'stage':'rejected'}))
            def fake(args,**kwargs):
                self.assertIn(str(retry.ROOT/'try-long-segment.py'),args)
                return type('Result',(),{'stdout':json.dumps({'state':'no_clean_eight_second_segment'})})()
            with patch.object(retry,'run',side_effect=fake):retry.main(path)
            state=json.loads((retry.ROOT/'production-runs/cabin08-retry-20261120/state.json').read_text())
            self.assertEqual(state['stage'],'submission_slots_exhausted_no_image_purchase')
            self.assertEqual(state['completed_video_attempts'],2)

    def test_model_outage_does_not_block_other_model_and_real_result_resets_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_files(Path(tmp))
            for i in (1,2):
                (retry.STATE/f'runway-failed{i}.json').write_text(json.dumps({
                    'state':'generation_failed','model':'Gen-4.5 Image to Video','created':i}))
            self.assertEqual(retry.model_failures('Gen-4 Turbo'),0)
            self.assertEqual(retry.model_failures('Gen-4.5 Image to Video'),2)
            (retry.STATE/'runway-ready.json').write_text(json.dumps({
                'state':'generated_needs_download','model':'Gen-4.5 Image to Video','created':3}))
            self.assertEqual(retry.model_failures('Gen-4.5 Image to Video'),0)

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
                elif str(retry.ROOT / 'try-long-segment.py') in args:
                    return type('Result', (), {'stdout': json.dumps({'state':'no_clean_eight_second_segment'})})()
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

    def test_ready_video_download_failure_recovers_without_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            shutil.copyfile(Path(__file__).with_name('follow-generation.py'),retry.ROOT/'follow-generation.py')
            rid=config['sources'][0]['attempts'][0]
            ledger=retry.STATE/('runway-'+rid+'.json')
            ledger.write_text(json.dumps({'state':'generated_needs_download',
                'video_url':'https://r2.syntx.ai/generated/test-result.mp4'}))
            calls=[]
            def fake(args,**kwargs):
                calls.append(args)
                if '/app/retry-download.py' in args:
                    ledger.write_text(json.dumps({'state':'downloaded_needs_qc'}))
                elif str(retry.ROOT/'pipeline-one.py') in args:
                    p=retry.ROOT/'assets'/rid/'pipeline.json'
                    p.write_text(json.dumps({'stage':'held_for_motion_and_audio_review','preview':'checked.mp4'}))
                else:self.fail('Unexpected generation or paid action: '+str(args))
                return type('Result',(),{'stdout':'{}'})()
            with patch.object(retry,'run',side_effect=fake):retry.main(path)
            self.assertEqual(len([x for x in calls if '/app/retry-download.py' in x]),1)
            self.assertFalse(any('/app/runway_prepare.py' in x for x in calls))

    def test_provider_failures_do_not_buy_another_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,path=self.setup_files(Path(tmp))
            for i,rid in enumerate(config['sources'][0]['attempts']):
                p=retry.ROOT/'assets'/rid;p.mkdir(parents=True)
                (p/'pipeline.json').write_text(json.dumps({'stage':'rejected'}))
                if i<2:(retry.STATE/('runway-'+rid+'.json')).write_text(json.dumps({
                    'state':'generation_failed','created':i+1}))
            def fake(args,**kwargs):
                self.assertIn(str(retry.ROOT/'try-long-segment.py'),args)
                return type('Result',(),{'stdout':json.dumps({'state':'no_clean_eight_second_segment'})})()
            with patch.object(retry,'run',side_effect=fake):retry.main(path)
            state=json.loads((retry.ROOT/'production-runs/cabin08-retry-20261120/state.json').read_text())
            self.assertEqual(state['stage'],'provider_unavailable_no_image_purchase')


if __name__=='__main__':unittest.main()
