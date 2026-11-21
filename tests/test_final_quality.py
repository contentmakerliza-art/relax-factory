import unittest
from types import SimpleNamespace
from render.quality import apply_queue_quality,apply_render_quality

class QualityTests(unittest.TestCase):
    def test_waiting_detailed_channels_use_eight_mbps(self):
        for channel in ['Mountain View Cafe','Little Paris Jazz Cafe','Quiet Pines Cabin']:
            item={'channel':channel,'bitrate':4,'ready':False}
            self.assertTrue(apply_queue_quality(item));self.assertEqual(item['bitrate'],8)
            self.assertFalse(apply_queue_quality(item))
    def test_no_changes_to_ready_files_or_black_screen(self):
        for item in [{'channel':'Mountain View Cafe','ready':True,'bitrate':4},
                     {'channel':'Exhale to Sleep','bitrate':4}]:
            before=dict(item);self.assertFalse(apply_queue_quality(item));self.assertEqual(before,item)
    def test_higher_quality_is_preserved(self):
        item={'channel':'Quiet Pines Cabin','bitrate':15}
        settings=SimpleNamespace(width=3840,height=2160,audio_bitrate='192k',video_bitrate='4M')
        apply_render_quality(item,settings)
        self.assertEqual((settings.width,settings.height,settings.video_bitrate,settings.audio_bitrate),(3840,2160,'15M','320k'))
    def test_low_resolution_recipe_is_raised_only_for_target_channels(self):
        item={'channel':'Little Paris Jazz Cafe','bitrate':4}
        settings=SimpleNamespace(width=1280,height=720,audio_bitrate='128k',video_bitrate='4M')
        apply_render_quality(item,settings)
        self.assertEqual((settings.width,settings.height,settings.video_bitrate),(1920,1080,'8M'))

if __name__=='__main__':unittest.main()
