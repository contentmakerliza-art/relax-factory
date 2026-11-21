"""Final upload quality for detailed winter scenes; ready files remain untouched."""
from __future__ import annotations

VERSION = '2026-11-21-fullhd-8mbps'
CHANNELS = {'Little Paris Jazz Cafe', 'Quiet Pines Cabin', 'Mountain View Cafe'}
PROFILES = {'Little_Paris_Jazz_Cafe', 'Quiet_Pines', 'Mountain_View_Cafe'}
MIN_VIDEO_MBPS = 8


def applies(item: dict) -> bool:
    return not item.get('ready') and (item.get('channel') in CHANNELS or item.get('user') in PROFILES)


def apply_queue_quality(item: dict) -> bool:
    if not applies(item):
        return False
    before = item.get('bitrate')
    item['bitrate'] = max(MIN_VIDEO_MBPS, int(before or 0))
    item['quality_policy'] = VERSION
    return before != item['bitrate']


def apply_render_quality(item: dict, settings) -> None:
    if not applies(item):
        return
    apply_queue_quality(item)
    settings.video_bitrate = f"{item['bitrate']}M"
    # Existing higher-resolution recipes are preserved. Do not fabricate 4K.
    if settings.width < 1920 or settings.height < 1080:
        settings.width, settings.height = 1920, 1080
    settings.audio_bitrate = '320k'
