"""Edit one owner-authorized local Cabin source in ordinary Banana 2 via SYNTX UI."""
from pathlib import Path
import json
import os
import re
import time
from browser_lease import browser_lease
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


def main(request=None):
    if request is None:raise ValueError('Explicit prepared image request required')
    source=Path('/downloads/cabin-18-source.jpg')
    ledger=Path('/state/cabin18-reflection-edit-v1.json')
    if request is None and ledger.exists():
        print(json.dumps({'existing':json.loads(ledger.read_text())}));return
    prompt=('Edit the attached image as the actual target. Preserve the same camera, room, '
        'stone chimney outline, black fireplace frame, wood furniture, green chair, gray chair, '
        'windows and snowy forest. Remove ONLY the bright window-shaped reflection inside '
        'the fireplace. The hearth interior is matte dark firebrick with the same small natural '
        'wood fire. Keep the original stonework and opening geometry with matte surfaces. '
        'The same ginger cat sleeps tightly curled on the gray chair with its chin resting '
        'on its paws, eyes closed and relaxed ears. Preserve its natural anatomy and scale. '
        'No snow or particles inside the room. Photorealistic, same wide 16:9 composition.')
    output_name='cabin18-no-reflection-v1'
    if request is not None:
        if set(request)!={'request_id','source','prompt'}:
            raise ValueError('Unexpected edit request fields')
        if not re.fullmatch(r'cabin(?:03|05|06|07|09|10|11|12|15|19|20|21)-source-new-v[12]-20261121',request['request_id']):
            raise ValueError('Unsupported edit request ID')
        source=Path(request['source']).resolve()
        if source.parent!=Path('/downloads') or not source.is_file():
            raise ValueError('Expected a staged source image')
        prompt=request['prompt']
        if not isinstance(prompt,str) or not 1<=len(prompt)<=4000:raise ValueError('Invalid prompt')
        ledger=Path('/state')/(request['request_id']+'.json')
        if ledger.exists():
            print(json.dumps({'existing':json.loads(ledger.read_text())}));return
        output_name=request['request_id']
    with browser_lease():
        active=active_cabin_requests()
        if len(active)>=2:
            print(json.dumps({'busy':True,'active':active}));return
        with sync_playwright() as p:
            b=p.chromium.connect_over_cdp('http://127.0.0.1:9222',artifacts_dir='/downloads')
            if len(b.contexts)!=1:raise RuntimeError('Expected one authorized browser profile')
            page=b.contexts[0].new_page();page.set_viewport_size({'width':1920,'height':1080});page.set_default_timeout(20000)
            target_id=b.contexts[0].new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId']
            original=page.url
            try:
                page.goto('https://syntx.ai/ru/image/banana',wait_until='domcontentloaded')
                field=page.get_by_placeholder('Напишите ваш промпт...',exact=True);field.wait_for(state='visible',timeout=45000)
                model=page.locator('[data-cy="ai-model-select-dropdown-menu"]')
                if model.count()!=1 or model.locator('.el-select__wrapper').inner_text().strip()!='Banana 2':
                    raise ValueError('Ordinary Banana 2 must be selected')
                form=page.locator('form').filter(has=field)
                if form.locator('.uploaded-files__list img').count():raise ValueError('Unexpected references')
                ratio=form.locator('.form-settings__badge').filter(has=page.locator('.form-settings__ratio-box'))
                ratio.locator('.el-select__wrapper').click()
                page.get_by_role('option',name=re.compile(r'^16:9(?:\s|$)')).click()
                if not form.locator('.form-settings__badge').filter(has_text='2K').count():raise ValueError('Expected 2K')
                form.locator('input[type=file]').set_input_files(str(source))
                page.wait_for_function('()=>{let a=[...document.querySelectorAll("form .uploaded-files__list img")];return a.length===1&&a[0].complete&&a[0].naturalWidth>0}',timeout=60000)
                field.fill(prompt)
                cost=form.locator('.send-actions__cost').inner_text().strip()
                if not 0<float(cost.replace(',','.'))<=3:raise ValueError('Expected at most 3 SYNTX tokens')
                button=form.locator('button.send-actions__send')
                if not button.is_enabled():raise ValueError('Generation not ready')
                before=page.locator('.bot-image-message').count()
                record={'state':'submission_uncertain','cost_tokens':cost,'prompt':prompt,'created':time.time(),'async_submission':True,'request_id':request['request_id'],'browser_target_id':target_id}
                with ledger.open('x') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
                button.click();record['state']='submitted';ledger.write_text(json.dumps(record))
                page.wait_for_url(re.compile(r'https://syntx\.ai/ru/image/banana/[a-f0-9-]{36}'),timeout=30000)
                record.update(chat_url=page.url,before_count=before,request_id=request['request_id'],async_submission=True)
                ledger.write_text(json.dumps(record))
                print(json.dumps({'state':'submitted','request_id':request['request_id'],'browser_target_id':target_id}))
            finally:
                keep=bool(ledger.exists() and json.loads(ledger.read_text()).get('state')=='submitted')
                if not keep:page.close()



if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request')
    args=parser.parse_args();main(json.loads(Path(args.request).read_text()) if args.request else None)
