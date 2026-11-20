"""Numerical prescreen limits at 1280x720, never owner approval.

The owner explicitly permits barely perceptible flank breathing. It must not
be treated as the same motion as a head, paw or fixed wall moving.
"""
import math

VERSION='2026-11-20-subtle-breathing-v2'
LIMITS={'head':1.0,'paws':1.0,'wall':1.0,'flank':2.0}


def moving_regions(report):
    moving=[]
    for name,limit in LIMITS.items():
        values=[report[name]['x_range_pixels'],report[name]['y_range_pixels']]
        if any(not math.isfinite(v) or v>limit for v in values):moving.append(name)
    return moving
