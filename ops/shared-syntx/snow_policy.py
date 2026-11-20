"""Snow motion for future Cabin submissions; never change another channel's workflow."""
import re

VERSION = '2026-11-20-fine-wind-snow-v1'
SNOW = (
    'Many small fine snowflakes fall visibly outdoors behind the glass. '
    'Gentle irregular wind gusts carry them diagonally, gradually shifting left and right '
    'with natural variation between flakes. Wind and intensity agree across windows; '
    'frames and indoor objects occlude the snow. Keep the landscape readable. '
)


def compose(prompt, request_id):
    # Little Paris uses its existing separate snowfall layer, Exhale has no snow.
    # These channels and other projects must retain their supplied prompts.
    if not re.fullmatch(r'cabin(?:08|22)-fullframe-v\d+-20261120', request_id or ''):
        return prompt, None
    sentences = re.split(r'(?<=[.!?])\s+', prompt.strip())
    remainder = ' '.join(s for s in sentences if not re.search(
        r'\bsnow(?:flakes|fall)?\b|^It is distant, behind the glass', s, re.I))
    result = SNOW + remainder
    if len(result) > 1000:
        raise ValueError('Snow policy exceeds Runway prompt budget; revise explicitly')
    return result, VERSION
