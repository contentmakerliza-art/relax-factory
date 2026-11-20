import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('finisher',Path(__file__).with_name('finish-production.py'))
finisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(finisher)

class StopTest(Exception):pass


class FinisherStartupTests(unittest.TestCase):
    def setup_case(self,root):
        finisher.ROOT=root
        configs=root/'production-configs';configs.mkdir()
        group='cabin22-retry-20261120';(configs/(group+'.json')).write_text('{}')
        folder=root/'production-runs'/group;folder.mkdir(parents=True)
        (folder/'state.json').write_text(json.dumps({'stage':'preparation_failed_no_submission'}))
        (folder/'delivery.json').write_text(json.dumps({'stage':'held_for_inspection'}))
        return group,folder

    def test_stale_failure_is_not_notified_during_producer_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            group,folder=self.setup_case(Path(tmp))
            with patch.object(finisher.time,'monotonic',side_effect=[0,1,1]),patch.object(finisher.time,'sleep',side_effect=StopTest),patch.object(finisher,'notify_hold') as notify:
                with self.assertRaises(StopTest):finisher.finish(group,folder)
                notify.assert_not_called()
            self.assertEqual(json.loads((folder/'delivery.json').read_text())['stage'],'waiting_for_checked_preview')

    def test_persistent_failure_after_grace_requires_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            group,folder=self.setup_case(Path(tmp))
            with patch.object(finisher.time,'monotonic',side_effect=[0,31,31]),patch.object(finisher,'notify_hold') as notify:
                finisher.finish(group,folder);notify.assert_called_once()
            self.assertEqual(json.loads((folder/'delivery.json').read_text())['stage'],'held_for_inspection')


if __name__=='__main__':unittest.main()
