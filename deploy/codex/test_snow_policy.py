import unittest
from snow_policy import compose,VERSION,raw_snow_deferred
class SnowPolicyTest(unittest.TestCase):
 def test_cabin_removes_snow_and_keeps_fire_cat_and_camera(self):
  for rid in ['cabin22-fullframe-v12-20261120','cabin11-fullframe-v2-20261121','cabin05-fullframe-v1-20261122']:
   prompt,version=compose('Dense snowfall outside. Hundreds of small flakes drift diagonally. Keep the camera locked. Animate the existing fireplace.',rid)
   self.assertEqual(version,VERSION)
   self.assertNotRegex(prompt.lower(),r'snow|flake')
   self.assertIn('existing fireplace',prompt);self.assertIn('breathing',prompt)
   self.assertIn('Locked tripod',prompt);self.assertLessEqual(len(prompt),1000)
 def test_other_channels_and_projects_unchanged(self):
  for rid in ('little-paris-22','exhale-22','mountain-view-22',None):
   self.assertEqual(compose('Snowfall outside.',rid),('Snowfall outside.',None))
 def test_no_silent_truncation(self):
  with self.assertRaises(ValueError):compose('Rigid geometry. '*100,'cabin08-fullframe-v5-20261120')
 def test_raw_snow_deferred_only_for_new_policy_not_archives_or_derived(self):
  self.assertTrue(raw_snow_deferred('cabin11-fullframe-v2-20261122',{'snow_policy_version':VERSION}))
  self.assertFalse(raw_snow_deferred('cabin11-fullframe-v1-20261121',{'snow_policy_version':'old'}))
  self.assertFalse(raw_snow_deferred('cabin11-snow-v1-20261121',{'kind':'owner_requested_window_snow_prototype'}))
  self.assertFalse(raw_snow_deferred('mountain-view-22',{'snow_policy_version':VERSION}))
if __name__=='__main__':unittest.main()
