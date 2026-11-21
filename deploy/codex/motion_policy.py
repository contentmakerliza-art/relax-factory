"""Numerical prescreen limits at 1280x720, never owner approval.

The owner explicitly permits barely perceptible flank breathing. It must not
be treated as the same motion as a head, paw or fixed wall moving.
"""
import math

VERSION='2026-11-21-visible-motion-v4-triage'
# Owner permits an additional half-pixel measurement margin; visual QC remains mandatory.
LIMITS={'head':1.5,'paws':1.5,'wall':1.5,'flank':2.0}


def moving_regions(report):
    moving=[]
    for name,limit in LIMITS.items():
        values=[report[name]['x_range_pixels'],report[name]['y_range_pixels']]
        if any(not math.isfinite(v) or v>limit for v in values):moving.append(name)
    return moving
