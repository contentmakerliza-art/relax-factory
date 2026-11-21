"""Prepare or explicitly submit one zero-cost Runway request; persist before clicking."""
import json
import os
import re
import time
from pathlib import Path
from browser_lease import browser_lease
from snow_policy import compose as compose_snow
from playwright.sync_api import sync_playwright


def active_cabin_requests():
    active=[]
    for path in Path('/state').glob('*cabin*-20261121.json'):
        try:r=json.loads(path.read_text())
        except (OSError,ValueError):continue
        if r.get('async_submission') and r.get('state') in ('submitted','submission_uncertain','generated_needs_download'):
            kind='video' if path.name.startswith('runway-') else 'image'
            rid=path.stem.removeprefix('runway-')
            active.append({'kind':kind,'request_id':rid})
    return active


def prepare(source, prompt, *, submit=False, request_id=None, model_name='Gen-4 Turbo'):
    original_prompt = prompt
    prompt, snow_policy_version = compose_snow(prompt, request_id)
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
        active=active_cabin_requests()
        if len(active)>=2:return {'busy':True,'active':active}
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9222', timeout=15000, artifacts_dir='/downloads')
            if len(browser.contexts)!=1:raise RuntimeError('Expected one authorized browser profile')
            page=browser.contexts[0].new_page()
            target_id=browser.contexts[0].new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId']
            # Compact layout exposes the model button used below. At 1920px
            # SYNTX moves those controls into a different settings sidebar.
            page.set_viewport_size({'width':1280,'height':900})
            original = 'https://syntx.ai/ru/video/runway'
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
                              'prompt': prompt, 'original_prompt': original_prompt,
                              'snow_policy_version': snow_policy_version,
                              'source': source.name, 'created': time.time(), 'async_submission':True, 'browser_target_id':target_id,
                              'model': model_name, 'seconds': 10, 'cost_tokens': 0}
                    # Persist BEFORE clicking. Even a crash cannot trigger an automatic retry.
                    with ledger.open('x') as handle:
                        json.dump(record, handle); handle.flush(); os.fsync(handle.fileno())
                    form.locator('button.send-actions__send').click()
                    record['state'] = 'submitted'
                    ledger.write_text(json.dumps(record))
                    page.wait_for_url(re.compile(r'https://syntx\.ai/ru/video/runway/[a-f0-9-]{36}'),timeout=30000)
                    record.update(chat_url=page.url,before_urls=before,async_submission=True)
                    ledger.write_text(json.dumps(record))
                    return {'submitted':True,'state':record['state'],'request_id':request_id,'chat_url':page.url}
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
                    keep=bool(ledger and ledger.exists() and json.loads(ledger.read_text()).get('state')=='submitted')
                    if not keep:page.close()



if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);a=p.parse_args()
    r=json.loads(Path(a.request).read_text())
    print(json.dumps(prepare(r['source'],r['prompt'],submit=True,request_id=r['request_id'],model_name=r.get('model','Gen-4 Turbo'))))
