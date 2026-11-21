import hashlib,os,tempfile,unittest
from pathlib import Path
from cabin_loop_recipe import VERSION,expected_loop_frames,safe_camera_fit,install_verified_master
class LoopRecipeTests(unittest.TestCase):
 def test_cycle_keeps_eight_seconds_and_has_one_seam(self):
  self.assertEqual(expected_loop_frames(240),222)
  self.assertEqual(expected_loop_frames(242),224)
  with self.assertRaises(ValueError):expected_loop_frames(72)
 def test_extreme_camera_changes_are_not_silently_repaired(self):
  self.assertTrue(safe_camera_fit(None))
  self.assertTrue(safe_camera_fit(([0,24],[(1,0,0),(1.01,2,1)])))
  self.assertFalse(safe_camera_fit(([0,24],[(1,0,0),(1.2,0,0)])))
  self.assertFalse(safe_camera_fit(([0,24],[(1,0,0),(1,20,0)])))
 def test_master_replacement_preserves_approved_hardlinked_preview(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'card';visual=folder/'visual';visual.mkdir(parents=True)
   preview=folder/'preview.mp4';preview.write_bytes(b'approved-preview');os.link(preview,visual/'approved-master.mp4')
   staged=root/'master.mp4';staged.write_bytes(b'cyclic-master')
   sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
   manifest={'loop_builder_version':VERSION,'publication_loop_mode':'repeat','preview_sha256':sha(preview),'loop_master_sha256':sha(staged)}
   install_verified_master(folder,staged,manifest);install_verified_master(folder,staged,manifest)
   self.assertEqual(preview.read_bytes(),b'approved-preview');self.assertEqual((visual/'approved-master.mp4').read_bytes(),b'cyclic-master')
   self.assertEqual(len(list(visual.iterdir())),1)
 def test_changed_master_cannot_replace_any_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);p=root/'master';p.write_bytes(b'wrong')
   with self.assertRaises(ValueError):install_verified_master(root,p,{'loop_builder_version':VERSION,'publication_loop_mode':'repeat','loop_master_sha256':'not-matching'})
   self.assertFalse((root/'visual').exists())
if __name__=='__main__':unittest.main()
