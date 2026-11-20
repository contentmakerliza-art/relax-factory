"""Prepare or explicitly submit one zero-cost Runway request; persist before clicking."""
import json
import os
import re
import time
from pathlib import Path
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright


def prepare(source, prompt, *, submit=False, request_id=None, model_name='Gen-4.5 Image to Video'):
    if model_name not in ('Gen-4.5 Image to Video','Gen-4 Turbo','Gen-4'):
        raise ValueError('Only explicitly supported image-to-video models are allowed')
    source = Path(source).resolve()
    if source.parent != Path('/downloads') or not source.is_file():
        raise ValueError('Expected an existing staged reference in /downloads')
    if not 1 <= len(prompt) <= 1000:
        raise ValueError('Runway prompt must be 1–1000 characters')
    with browser_lease():
        ledger = None
        if submit:
            if not request_id or not re.fullmatch(r'[a-z0-9-]{16,80}', request_id):
                raise ValueError('A stable request ID is required')
            ledger = Path('/state') / ('runway-' + request_id + '.json')
            if ledger.exists():
                return {'submitted': False, 'duplicate_blocked': True,
                        'previous': json.loads(ledger.read_text())}
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9222', timeout=15000, artifacts_dir='/downloads')
            if len(browser.contexts) != 1 or len(browser.contexts[0].pages) != 1:
                raise RuntimeError('Expected exactly one existing SYNTX tab')
            page = browser.contexts[0].pages[0]
            # Compact layout exposes the model button used below. At 1920px
            # SYNTX moves those controls into a different settings sidebar.
            page.set_viewport_size({'width':1280,'height':900})
            original = page.url
            if not original.startswith('https://syntx.ai/'):
                raise RuntimeError('Unexpected browser page')
            page.set_default_timeout(15000)
            attached_reference = False
            try:
                page.goto('https://syntx.ai/ru/video/runway', wait_until='domcontentloaded')
                textarea = page.get_by_placeholder('Напишите ваш промпт...', exact=True)
                textarea.wait_for(state='visible', timeout=45000)
                if page.get_by_role('dialog', name='Параметры изображения').is_visible():
                    raise RuntimeError('Unfinished reference from earlier operation; inspect first')
                model = page.locator('[data-cy="ai-model-select-dropdown-menu"]')
                if not model.is_visible():
                    page.locator('[data-cy="ai-select-menu-btn"]').click()
                model.locator('.el-select__wrapper').click()
                page.locator('[data-cy="ai-model-'+model_name+'"]').click()
                # Selecting a model closes the menu; do not click a hidden confirm button.
                for index, value in [(0, r'^16:9(?:\s|$)'), (1, r'^10 секунд$')]:
                    page.locator('form .form-settings__badge').nth(index).locator('.el-select__wrapper').click()
                    page.get_by_role('option', name=re.compile(value)).click()
                form = page.locator('form').filter(has=textarea)
                if form.locator('.uploaded-files__list img').count():
                    raise RuntimeError('Unexpected attached image; do not replace silently')
                page.locator('input[type=file]').set_input_files(str(source))
                attached_reference = True
                dialog = page.get_by_role('dialog', name='Параметры изображения')
                dialog.wait_for(state='visible')
                dialog.get_by_role('button', name='Подтвердить', exact=True).click()
                dialog.wait_for(state='hidden', timeout=60000)
                textarea.fill(prompt)
                cost = form.locator('.send-actions__cost')
                cost.wait_for(state='visible', timeout=30000)
                price = cost.inner_text().strip()
                if price not in ('0', '0.0', '0,0'):
                    raise RuntimeError('Runway is not verified free; do not generate')
                badges = form.locator('.form-settings__badge').all_text_contents()
                if len(badges) < 2 or '16:9' not in badges[0] or '10' not in badges[1]:
                    raise RuntimeError('Unexpected format or duration')
                if not form.locator('button.send-actions__send').is_enabled():
                    raise RuntimeError('Generation is not ready')
                if submit:
                    before = page.locator('video source').evaluate_all('(es)=>es.map(e=>e.src)')
                    record = {'request_id': request_id, 'state': 'submission_uncertain',
                              'prompt': prompt, 'source': source.name, 'created': time.time(),
                              'model': model_name, 'seconds': 10, 'cost_tokens': 0}
                    # Persist BEFORE clicking. Even a crash cannot trigger an automatic retry.
                    with ledger.open('x') as handle:
                        json.dump(record, handle); handle.flush(); os.fsync(handle.fileno())
                    form.locator('button.send-actions__send').click()
                    record['state'] = 'submitted'
                    ledger.write_text(json.dumps(record))
                    page.wait_for_function(
                        'old=>[...document.querySelectorAll("video source")].some(e=>e.src && !old.includes(e.src))',
                        arg=before, timeout=660000)
                    urls = page.locator('video source').evaluate_all('(es)=>es.map(e=>e.src)')
                    new = [url for url in urls if url and url not in before]
                    if len(new) != 1:
                        raise RuntimeError('Ambiguous video result; inspect history, never resubmit')
                    record.update(state='generated_needs_download', video_url=new[0], chat_url=page.url)
                    ledger.write_text(json.dumps(record))
                    page.set_viewport_size({'width':1920,'height':1080})
                    target_video = None
                    for video in page.locator('video').all():
                        if video.locator('source').get_attribute('src') == new[0]:
                            target_video = video
                            break
                    if target_video is None:
                        raise RuntimeError('Generated video disappeared; inspect saved request')
                    message = target_video.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," chat-message ")][1]')
                    with page.expect_download(timeout=60000) as download:
                        message.locator('[data-cy="download-file-btn"]').click()
                    output = Path('/downloads') / (request_id + '.mp4')
                    download.value.save_as(str(output))
                    if output.stat().st_size < 10000:
                        raise RuntimeError('Downloaded video is incomplete')
                    record.update(state='downloaded_needs_qc', file=str(output))
                    ledger.write_text(json.dumps(record))
                    return {'submitted': True, 'state': record['state'], 'request_id': request_id}
                return {'prepared': True, 'submitted': False, 'cost_tokens': 0,
                        'model': model_name, 'seconds': 10, 'ratio': '16:9'}
            except Exception:
                if submit and ledger and ledger.exists():
                    saved = json.loads(ledger.read_text())
                    if saved.get('state') == 'submitted':
                        saved['chat_url'] = page.url
                        body = page.locator('body').inner_text(timeout=5000)
                        if prompt in body and 'Request timed out - please try again' in body:
                            saved.update(state='generation_failed', error='Explicit SYNTX timeout')
                        else:
                            saved.update(state='submitted_needs_inspection', error='Result not confirmed; never resubmit blindly')
                        ledger.write_text(json.dumps(saved))
                raise
            finally:
                try:
                    if not submit and attached_reference:
                        # A quote must not leave its input image in the shared form.
                        references = page.locator('form [data-cy="uploaded-file"]')
                        own = [r for r in references.all() if (r.get_attribute('data-key') or '').startswith(source.name+'-')]
                        if len(own)==1:
                            dialog=page.get_by_role('dialog',name='Параметры изображения')
                            if dialog.is_visible():
                                dialog.get_by_role('button',name='Подтвердить',exact=True).click()
                                dialog.wait_for(state='hidden',timeout=60000)
                            if own[0].locator('button').count()!=1:raise RuntimeError('Inspect own quoted reference before clearing it')
                            own[0].locator('button').click()
                            page.wait_for_function('()=>document.querySelectorAll("form .uploaded-files__list img").length===0')
                finally:
                    page.goto(original, wait_until='domcontentloaded')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--request', default='/downloads/cabin-17-request.json')
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text())
    print(json.dumps(prepare(request.get('source', '/downloads/cabin-17-source.jpg'), request['prompt'],
                             submit=args.submit, request_id=request.get('request_id', 'cabin17-fullframe-v1-20261120'),
                             model_name=request.get('model','Gen-4.5 Image to Video'))))
