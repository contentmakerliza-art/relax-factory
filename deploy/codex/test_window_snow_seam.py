import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import window_snow_media as media

class SeamGateTests(unittest.TestCase):
 def frames(self):
  rng=np.random.default_rng(4);base=rng.normal(120,35,(48,48)).astype(np.float32)
  return np.repeat(base[None,:,:],48,axis=0)
 def test_stable_room_is_not_rejected_by_numeric_gate(self):
  values=self.frames()
  with patch.object(media,'patch_sequences',return_value=[values,values.copy(),values.copy()]):
   result=media.seam_quality(None,[],6)
  self.assertTrue(result['passed'])
 def test_transient_blurred_seam_is_flagged(self):
  values=self.frames();base=values[0]
  values[-6:]=(base+np.roll(base,1,axis=1))/2
  with patch.object(media,'patch_sequences',return_value=[values,values.copy(),values.copy()]):
   result=media.seam_quality(None,[],6)
  self.assertFalse(result['passed']);self.assertLess(result['minimum_edge_energy_ratio'],.75)
 def test_seam_sheet_uses_selected_frame_dictionary_without_full_video_buffer(self):
  with tempfile.TemporaryDirectory() as tmp:
   selected=bytes(7*1280*720*3)
   with patch.object(media.engine,'probe_duration',return_value=1),patch.object(media.subprocess,'run',return_value=SimpleNamespace(stdout=selected)):
    media.seam_sheet(Path('loop.mp4'),Path(tmp),[(60,40,32,32)]*3,3)
   self.assertTrue((Path(tmp)/'preview-seam.png').exists())
 def test_sharp_but_jumping_hard_cut_is_not_accepted(self):
  values=self.frames();values[-1]=np.roll(values[-1],2,axis=1)
  with patch.object(media,'patch_sequences',return_value=[values,values.copy(),values.copy()]):
   result=media.seam_quality(None,[],0)
  self.assertFalse(result['passed'])

if __name__=='__main__':unittest.main()
