"""Edit one owner-authorized local Cabin source in ordinary Banana 2 via SYNTX UI."""
from pathlib import Path
import json
import os
import re
import time
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright


def main(request=None):
    source=Path('/downloads/cabin-18-source.jpg')
    ledger=Path('/state/cabin18-reflection-edit-v1.json')
    if request is None and ledger.exists():
        print(json.dumps({'existing':json.loads(ledger.read_text())}));return
    prompt=('Edit the attached image as the actual target. Preserve the same camera, room, '
        'stone chimney outline, black fireplace frame, wood furniture, green chair, gray chair, '
        'windows and snowy forest. Remove ONLY the bright window-shaped reflection inside '
        'the fireplace. The hearth interior is matte dark firebrick with the same small natural '
        'wood fire. No reflective front glass, no reflected window, no mirror, no second firebox '
        'and no inserted rectangle. Keep the original stonework and opening geometry. '
        'The same ginger cat sleeps tightly curled on the gray chair with its chin resting '
        'on its paws, eyes closed and relaxed ears. Preserve its natural anatomy and scale. '
        'No snow or particles inside the room. Photorealistic, same wide 16:9 composition.')
    output_name='cabin18-no-reflection-v1'
    if request is not None:
        if set(request)!={'request_id','source','prompt'}:
            raise ValueError('Unexpected edit request fields')
        if not re.fullmatch(r'cabin(?:08|18|22)-source-(?:edit|new)-v[1-3]-20261120',request['request_id']):
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
        with sync_playwright() as p:
            b=p.chromium.connect_over_cdp('http://127.0.0.1:9222',artifacts_dir='/downloads')
            if len(b.contexts)!=1 or len(b.contexts[0].pages)!=1:raise ValueError('Unexpected browser session')
            page=b.contexts[0].pages[0];page.set_viewport_size({'width':1920,'height':1080});page.set_default_timeout(20000)
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
            record={'state':'submission_uncertain','cost_tokens':cost,'prompt':prompt,'created':time.time()}
            with ledger.open('x') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
            button.click();record['state']='submitted';ledger.write_text(json.dumps(record))
            page.wait_for_function('n=>document.querySelectorAll(".bot-image-message").length>n',arg=before,timeout=90000)
            message=page.locator('.bot-image-message').nth(before)
            img=message.locator('img.bot-image-item__image');img.wait_for(state='visible',timeout=300000)
            if img.count()!=1:raise ValueError('Ambiguous edit result')
            record.update(state='generated_needs_download',image_url=img.get_attribute('src'),chat_url=page.url);ledger.write_text(json.dumps(record))
            with page.expect_download(timeout=60000) as info:message.locator('[data-cy="download-file-btn"]').click()
            suffix=Path(info.value.suggested_filename).suffix.lower()
            if suffix not in ('.jpg','.png','.webp','.jpeg'):raise ValueError('Invalid image download')
            target=Path('/downloads')/(output_name+suffix)
            info.value.save_as(str(target))
            record.update(state='downloaded_needs_qc',file=str(target));ledger.write_text(json.dumps(record))
            print(json.dumps({'state':record['state'],'file':str(target),'cost_tokens':cost}))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request')
    args=parser.parse_args();main(json.loads(Path(args.request).read_text()) if args.request else None)
