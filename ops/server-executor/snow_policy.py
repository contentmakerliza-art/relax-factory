"""Cabin animation excludes snowfall; finished previews still require composited Snow."""
import re
VERSION = '2026-11-22-cabin-snow-at-assembly-v1'
CABIN_VIDEO_BASE = (
    'Locked tripod, fixed framing and perspective throughout. Animate only the natural flames '
    'inside the existing fireplace and barely perceptible slow flank breathing of the curled sleeping cat. '
    'Keep its head, paws and tail stable; slight natural ear motion is acceptable. '
    'Preserve the original firebox, logs, furniture, plants, wooden frames and masonry. '
    'The outdoor landscape stays still. Clear air, minimal plausible reflections and steady natural firelight.'
)
def is_cabin(request_id):
    return bool(re.fullmatch(r'cabin\d{2}-[a-z0-9-]+',request_id or ''))

def compose(prompt, request_id):
    if not is_cabin(request_id):return prompt,None
    # Old saved scene prompts may still request Snow. Never send these clauses.
    sentences=re.split(r'(?<=[.!?])\s+',prompt.strip())
    remainder=' '.join(s for s in sentences if not re.search(
        r'snow|flake|сне[гж]|снегопад|^It is distant, behind the glass',s,re.I))
    result=remainder if CABIN_VIDEO_BASE in remainder else CABIN_VIDEO_BASE+' '+remainder
    result=result.strip()
    if len(result)>1000:raise ValueError('Cabin animation prompt exceeds Runway limit; revise explicitly')
    return result,VERSION

def raw_snow_deferred(request_id, ledger):
    return is_cabin(request_id) and ledger.get('snow_policy_version')==VERSION
