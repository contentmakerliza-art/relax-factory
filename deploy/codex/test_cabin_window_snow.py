import importlib.util,unittest
from unittest.mock import patch
import cabin_window_snow as snow
import cabin_backlog_registry as registry

class WindowSnowTests(unittest.TestCase):
 @unittest.skipUnless(importlib.util.find_spec('PIL'),'Pillow runs in factory container')
 def test_new_masks_keep_fullhd_margin_and_feather_inside(self):
  mask=snow.make_glass_mask([[(10,10),(90,10),(90,90),(10,90)]],(100,100),output_size=(100,100))
  self.assertTrue(all(mask.getpixel((x,50))==0 for x in range(13)))
  self.assertGreater(mask.getpixel((14,50)),0)
  self.assertEqual(mask.getpixel((50,50)),255)
 @unittest.skipUnless(importlib.util.find_spec('PIL'),'Pillow runs in factory container')
 def test_margin_scales_with_render_resolution(self):
  mask=snow.make_glass_mask([[(10,10),(90,10),(90,90),(10,90)]],(100,100),output_size=(200,200),feather_output_px=0)
  self.assertEqual(mask.getpixel((11,50)),0)
  self.assertEqual(mask.getpixel((12,50)),255)
 def test_border_crop_preserves_aspect_and_moves_qa_regions(self):
  x,y=snow.FRAME_BORDER_CROP
  self.assertEqual((snow.WIDTH-2*x)*9,(snow.HEIGHT-2*y)*16)
  self.assertEqual(snow.transform_box([640,360,37,37]),[640,360,40,40])
 def test_only_explicit_owner_prototype_uses_existing_source(self):
  rows=[{'request_group':'cabin03-backlog-20261121','sources':[{'attempts':['cabin03-fullframe-v13-20261121','cabin03-fullframe-v15-20261121']}]}]
  with patch.object(registry,'records',return_value=rows):
   self.assertTrue(registry.attempt(snow.REQUEST,'cabin03-backlog-20261121'))
   self.assertFalse(registry.attempt('cabin11-snow-v15-20261121'))
   self.assertFalse(registry.attempt('cabin03-snow-v1-20261121'))
 def test_panes_stay_in_frame(self):
  for polygon in snow.PANES:
   for x,y in polygon:self.assertTrue(0<=x<snow.WIDTH and 0<=y<snow.HEIGHT)
 @unittest.skipUnless(importlib.util.find_spec('PIL'),'Pillow runs in factory container')
 def test_cat_fireplace_mullion_chair_and_sill_are_excluded(self):
  mask=snow.make_mask()
  self.assertTrue(all(mask.getpixel(point)==0 for point in snow.PROTECTED))
  for point in [(940,210),(705,280),(385,240)]:self.assertGreater(mask.getpixel(point),250)

if __name__=='__main__':unittest.main()
