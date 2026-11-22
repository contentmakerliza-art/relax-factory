"""No duplicate model, provider or delivery work after persistent checkpoints."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import mountain_batch as batch


class RecoveryTests(unittest.TestCase):
    def test_unknown_video_submission_never_triggers_a_retry(self):
        row={'state':'submitted','video_url':'https://r2.syntx.ai/example.mp4'}
        with patch.object(batch,'run') as run:
            self.assertIs(batch.recover_video('mountain22-native-v1-20261122',row),row)
            run.assert_not_called()

    def test_uncertain_paid_image_is_held_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(batch,'BATCH',Path(tmp)),patch.object(batch,'image_job',return_value={'state':'uncertain'}),patch.object(batch,'run') as run:
            cfg={'request_id':'mountain22-backlog-20261122','episode':22,'date':'2026-12-09','image_job_id':'a'*32}
            batch.process(cfg)
            state=json.loads((Path(tmp)/cfg['request_id']/'state.json').read_text())
            self.assertEqual(state['stage'],'held');self.assertEqual(state['reason'],'uncertain');run.assert_not_called()

    def test_delivered_preview_does_not_recheck_or_resend(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(batch,'BATCH',Path(tmp)),patch.object(batch,'judge') as judge,patch.object(batch,'run') as run:
            cfg={'request_id':'mountain22-backlog-20261122'};folder=Path(tmp)/cfg['request_id'];folder.mkdir()
            (folder/'state.json').write_text('{"stage":"delivered"}')
            batch.process(cfg);judge.assert_not_called();run.assert_not_called()

    def test_paid_source_replacement_limit_stops_spending(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(batch,'run') as run:
            folder=Path(tmp)
            batch.replace_source({'source_round':2},folder,['visual defect'])
            self.assertEqual(json.loads((folder/'state.json').read_text())['reason'],'bounded_new_images_exhausted')
            run.assert_not_called()


if __name__=='__main__':unittest.main()
