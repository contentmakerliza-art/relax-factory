"""Poll one exact isolated SYNTX chat briefly, release browser between polls.
No submission, no paid retry. Existing browser lease protects shared navigation.
"""
import argparse,json,re,time
from pathlib import Path
from urllib.parse import urlsplit
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright

def poll(kind,rid):
    if kind not in ('image','video') or not re.fullmatch(r'[a-z0-9-]{16,80}',rid):raise ValueError('Bad request')
    path=Path('/state')/(('runway-' if kind=='video' else '')+rid+'.json')
    with browser_lease():
        record=json.loads(path.read_text())
        if record['state'] in ('downloaded_needs_qc','generation_failed'):return {'state':record['state']}
        if record['state'] not in ('submitted','generated_needs_download') or not record.get('async_submission'):
            return {'state':'inspection_required','original_state':record['state']}
        chat=urlsplit(record['chat_url']);prefix='/ru/video/runway/' if kind=='video' else '/ru/image/banana/'
        if chat.scheme!='https' or chat.netloc!='syntx.ai' or not re.fullmatch(re.escape(prefix)+r'[a-f0-9-]{36}',chat.path):raise ValueError('Unexpected generation chat')
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222',timeout=15000,artifacts_dir='/downloads')
            if len(browser.contexts)!=1:raise ValueError('Expected one authorized browser profile')
            context=browser.contexts[0];page=None;created=False
            for candidate in context.pages:
                target=context.new_cdp_session(candidate).send('Target.getTargetInfo')['targetInfo']['targetId']
                if target==record.get('browser_target_id'):page=candidate;break
            if page is None:page=context.new_page();created=True
            try:
                page.set_viewport_size({'width':1920,'height':1080});page.set_default_timeout(12000)
                if created or page.url!=record['chat_url']:page.goto(record['chat_url'],wait_until='domcontentloaded')
                page.get_by_placeholder('Напишите ваш промпт...',exact=True).wait_for(state='visible',timeout=45000)
                page.wait_for_timeout(1500)
                body=page.locator('body').inner_text()
                # The first async implementation closed its temporary tab too early.
                # Retire only those inspected zero-cost legacy video clients, never
                # a paid image or a currently tracked live browser target.
                legacy_blank=(kind=='video' and created and not record.get('browser_target_id')
                    and record.get('cost_tokens')==0 and record['prompt'][:100] not in body)
                if legacy_blank:
                    record['empty_chat_checks']=record.get('empty_chat_checks',0)+1
                    record['last_empty_chat_check']=time.time();path.write_text(json.dumps(record))
                    if record['empty_chat_checks']>=2 and time.time()-record['created']>300:
                        record.update(state='client_result_lost_no_download',error='Legacy temporary client closed before result; two independent inspections found no submitted prompt in its saved chat',checked=time.time())
                        path.write_text(json.dumps(record));return {'state':record['state']}
                if 'Request timed out - please try again' in body and record['prompt'][:100] in body:
                    record.update(state='generation_failed',error='Explicit SYNTX timeout');path.write_text(json.dumps(record));return {'state':record['state']}
                if kind=='video':
                    prior=record.get('before_urls',[])
                    videos=[v for v in page.locator('video').all() if v.locator('source').count()==1 and v.locator('source').get_attribute('src') not in prior]
                    if len(videos)>1:raise ValueError('Ambiguous video result; inspect exact chat')
                    if not videos:return {'state':'submitted'}
                    video=videos[0];url=video.locator('source').get_attribute('src')
                    if not url:return {'state':'submitted'}
                    message=video.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," chat-message ")][1]')
                    target=Path('/downloads')/(rid+'.mp4');record.update(video_url=url)
                else:
                    messages=page.locator('.bot-image-message');before=record['before_count']
                    if messages.count()<=before:return {'state':'submitted'}
                    if messages.count()!=before+1:raise ValueError('Ambiguous image result')
                    message=messages.nth(before);image=message.locator('img.bot-image-item__image')
                    if image.count()!=1 or not image.is_visible():return {'state':'submitted'}
                    url=image.get_attribute('src')
                    if not url:return {'state':'submitted'}
                    record.update(image_url=url);target=None
                record.update(state='generated_needs_download');path.write_text(json.dumps(record))
                with page.expect_download(timeout=60000) as download:message.locator('[data-cy="download-file-btn"]').click()
                if target is None:
                    suffix=Path(download.value.suggested_filename).suffix.lower()
                    if suffix not in ('.jpg','.jpeg','.png','.webp'):raise ValueError('Invalid image type')
                    target=Path('/downloads')/(rid+suffix)
                if target.exists():raise ValueError('Existing file requires inspection')
                download.value.save_as(str(target))
                if target.stat().st_size<10000:raise ValueError('Incomplete generated file')
                record.update(state='downloaded_needs_qc',file=str(target),completed=time.time())
                path.write_text(json.dumps(record));return {'state':record['state'],'file':str(target)}
            finally:
                saved=json.loads(path.read_text())
                if created or saved['state'] not in ('submitted','generated_needs_download'):page.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind');p.add_argument('request_id');a=p.parse_args()
    print(json.dumps(poll(a.kind,a.request_id)))
