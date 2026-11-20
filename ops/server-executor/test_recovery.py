import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('recovery',Path(__file__).with_name('recover-production.py'))
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setup_case(self,root,success=20,paused=False):
        recovery.ROOT=root/'executor';recovery.STATE=root/'state';recovery.STATE.mkdir()
        folder=recovery.ROOT/'production-runs/cabin22-retry-20261120';folder.mkdir(parents=True)
        configs=recovery.ROOT/'production-configs';configs.mkdir()
        (configs/'cabin22-retry-20261120.json').write_text(json.dumps({'paused_by_owner':paused}))
        (folder/'state.json').write_text(json.dumps({'stage':'provider_unavailable_no_image_purchase'}))
        (folder/'delivery.json').write_text(json.dumps({'stage':'held_for_inspection'}))
        (recovery.STATE/'runway-failed.json').write_text(json.dumps({'state':'generation_failed','created':10}))
        (recovery.STATE/'runway-success.json').write_text(json.dumps({'state':'downloaded_needs_qc','created':success}))
        return folder

    def test_fresh_success_resumes_worker_and_delivery_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self.setup_case(Path(tmp))
            with patch.object(recovery,'launch') as launch:
                recovery.main();recovery.main()
                self.assertEqual(launch.call_count,2)
                self.assertTrue(any('production-retry.py' in str(c) for c in launch.call_args_list))
                self.assertTrue(any('finish-production.py' in str(c) for c in launch.call_args_list))
            self.assertEqual(json.loads((folder/'health-recovery.json').read_text())['state'],'started')

    def test_old_success_does_not_resume_or_buy_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_case(Path(tmp),success=5)
            with patch.object(recovery,'launch') as launch:
                recovery.main();launch.assert_not_called()

    def test_owner_pause_takes_precedence_over_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_case(Path(tmp),paused=True)
            with patch.object(recovery,'launch') as launch:
                recovery.main();launch.assert_not_called()


if __name__=='__main__':unittest.main()
