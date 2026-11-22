import unittest
from snow_policy import compose, VERSION


class SnowPolicyTest(unittest.TestCase):
    def test_cabin_preserves_cat_camera_and_fire(self):
        original = ('Many fine snowflakes fall steadily outdoors behind the window glass. '
                    'The camera is locked. The cat head and paws stay still. '
                    'Small flames move inside the original hearth.')
        prompt, version = compose(original, 'cabin22-fullframe-v12-20261120')
        self.assertEqual(version, VERSION)
        self.assertIn('gradually shifting left and right', prompt)
        self.assertIn('The cat head and paws stay still.', prompt)
        self.assertIn('The camera is locked.', prompt)
        self.assertIn('Small flames move inside the original hearth.', prompt)
        self.assertNotIn('fall steadily', prompt)
        self.assertLessEqual(len(prompt), 1000)

    def test_other_channels_and_projects_unchanged(self):
        for rid in ('little-paris-22', 'exhale-22', 'mountain-view-22', None):
            self.assertEqual(compose('Steam only, separate snow layer.', rid),
                             ('Steam only, separate snow layer.', None))

    def test_no_silent_truncation(self):
        with self.assertRaises(ValueError):
            compose('Rigid geometry. ' * 100, 'cabin08-fullframe-v5-20261120')
