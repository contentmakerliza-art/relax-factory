import ast,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import cabin_backlog_registry as registry

class BacklogTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'request_group':'cabin03-backlog-20261121','sources':[{'attempts':['cabin03-fullframe-v1-20261121']}]}]
    def test_only_exact_prepared_ids_and_derived_versions(self):
        with patch.object(registry,'records',return_value=self.rows):
            self.assertTrue(registry.attempt('cabin03-fullframe-v1-20261121','cabin03-backlog-20261121'))
            self.assertTrue(registry.attempt('cabin03-clean-v1-20261121'))
            for rid in ['../cabin03-fullframe-v1-20261121','cabin04-fullframe-v1-20261121','cabin03-fullframe-v2-20261121']:
                self.assertFalse(registry.attempt(rid))
            self.assertFalse(registry.attempt('cabin03-fullframe-v1-20261121','cabin05-backlog-20261121'))
    def test_geometry_bounds_include_search_padding(self):
        self.assertEqual(registry.validate_box([3,3,12,12]),[3,3,12,12])
        for box in [[0,0,20,20],[1200,700,100,30],[3,3,2,20],[3.0,3,20,20]]:
            with self.assertRaises(ValueError):registry.validate_box(box)
    def test_all_batch_stages_use_registry_not_pilot_coordinates(self):
        base=Path(__file__).parent/'cabin-backlog'
        for name in ['pipeline-one.py','try-long-segment.py','final-preview-review.py','deliver-preview.py']:
            source=(base/name).read_text();ast.parse(source)
            self.assertIn('backlog.attempt(',source,name)
        source=(base/'head-motion.py').read_text()
        self.assertIn("regions=backlog.geometry(request_id)['regions']",source)
        source=(base/'final-preview-review.py').read_text()
        self.assertIn("snow_crop=backlog.geometry(rid)['snow_crop']",source)
        self.assertIn("fps=1/5,scale=1280:720,crop=",source)
    def test_worker_limits_and_uncertain_submission_hold(self):
        source=(Path(__file__).parent/'cabin-backlog/production-retry.py').read_text()
        self.assertIn('MAX_ATTEMPTS = 3',source)
        self.assertIn("'recover_existing_video' if generation else",source)
        self.assertIn('if failures >= 2:',source)
        self.assertIn('>2:',source)
        self.assertIn('backlog.prepare_geometry(job, index',source)

if __name__=='__main__':unittest.main()
