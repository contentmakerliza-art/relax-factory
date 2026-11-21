import unittest
from motion_policy import moving_regions


def report(head=.9,flank=1.57):
    return {name:{'x_range_pixels':value,'y_range_pixels':.1} for name,value in
            [('head',head),('paws',.7),('wall',.11),('flank',flank)]}


class MotionPolicyTests(unittest.TestCase):
    def test_barely_perceptible_breathing_does_not_reject_fixed_head(self):
        self.assertEqual(moving_regions(report()),[])
    def test_head_motion_is_flagged_for_visual_review(self):
        self.assertEqual(moving_regions(report(head=1.6)),['head'])
    def test_owner_allowed_half_pixel_margin_still_requires_visual_review(self):
        self.assertEqual(moving_regions(report(head=1.05)),[])
        self.assertEqual(moving_regions(report(head=1.5)),[])
    def test_large_flank_motion_and_invalid_values_remain_rejected(self):
        self.assertEqual(moving_regions(report(flank=3)),['flank'])
        self.assertEqual(moving_regions(report(head=float('nan'))),['head'])


if __name__=='__main__':unittest.main()
