"""Download one already generated Runway result through the existing SYNTX UI.

Never submits a generation. Run in marketplace-syntx-studio.
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright


def main(request_id):
    if not re.fullmatch(r'cabin(?:08|22)-fullframe-v(?:[1-9]|1[0-8])-20261120', request_id):
        raise ValueError('Unsupported prepared result')
    ledger = Path('/state') / ('runway-' + request_id + '.json')
    with browser_lease():
        record = json.loads(ledger.read_text())
        if record['state'] == 'downloaded_needs_qc':
            return
        if record['state'] != 'generated_needs_download':
            raise ValueError('No confirmed generated video to download')
        if record.get('download_retries', 0) >= 3:
            raise ValueError('Three download retries exhausted; inspect saved result')
        chat = urlsplit(record['chat_url'])
        video = urlsplit(record['video_url'])
        if chat.scheme != 'https' or chat.netloc != 'syntx.ai' or not re.fullmatch(r'/ru/video/runway/[a-f0-9-]{36}', chat.path):
            raise ValueError('Unexpected saved chat URL')
        if video.scheme != 'https' or video.netloc != 'r2.syntx.ai':
            raise ValueError('Unexpected video origin')
        record['download_retries'] = record.get('download_retries', 0) + 1
        ledger.write_text(json.dumps(record))
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp('http://127.0.0.1:9222', artifacts_dir='/downloads')
            if len(b.contexts) != 1 or len(b.contexts[0].pages) != 1:
                raise ValueError('Expected one existing SYNTX tab')
            page = b.contexts[0].pages[0]
            original = page.url
            page.set_viewport_size({'width': 1920, 'height': 1080})
            try:
                page.goto(record['chat_url'], wait_until='domcontentloaded')
                page.wait_for_function('url=>[...document.querySelectorAll("video source")].some(e=>e.src===url)',
                                       arg=record['video_url'], timeout=60000)
                targets = [v for v in page.locator('video').all()
                           if v.locator('source').get_attribute('src') == record['video_url']]
                if len(targets) != 1:
                    raise ValueError('Ambiguous video in saved chat')
                message = targets[0].locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," chat-message ")][1]')
                target = Path('/downloads') / (request_id + '.mp4')
                if target.exists():
                    raise ValueError('Existing result requires inspection; do not overwrite')
                with page.expect_download(timeout=60000) as pending:
                    message.locator('[data-cy="download-file-btn"]').click()
                pending.value.save_as(str(target))
                if target.stat().st_size < 10000:
                    raise ValueError('Incomplete video file')
                record.update(state='downloaded_needs_qc', file=str(target))
                ledger.write_text(json.dumps(record))
            finally:
                page.goto(original, wait_until='domcontentloaded')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
