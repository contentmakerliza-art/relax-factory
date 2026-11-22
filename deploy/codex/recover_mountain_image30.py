"""Download the one inspected existing Banana result, never generate again."""
import base64,json,sys,re
from pathlib import Path
from urllib.parse import urlsplit
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright
from studio_tools import QUEUE,ASSETS

JOB='c1daaaf99ae898714ad1eb7e99b90f53'
CHAT='https://syntx.ai/ru/image/banana/b3739762-2f2e-467e-a9aa-5abaa8e32676'
if len(sys.argv)==3:JOB,CHAT=sys.argv[1:]
if not re.fullmatch('[0-9a-f]{32}',JOB) or not re.fullmatch('https://syntx.ai/ru/image/banana/[0-9a-f-]{36}',CHAT):
    raise ValueError('Unexpected inspected result identity')
job=QUEUE.get(JOB)
if 'Mountain View Cafe' not in job['payload']['prompt']:raise ValueError('Different project task preserved')
if job['state']=='completed':print('already recovered');raise SystemExit
if job['state']!='uncertain':raise ValueError('Unexpected task state')
with browser_lease():
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222',artifacts_dir='/downloads')
        if len(browser.contexts)!=1:raise ValueError('Unexpected browser profiles')
        page=browser.contexts[0].pages[0] if browser.contexts[0].pages else browser.contexts[0].new_page()
        page.set_viewport_size({'width':1920,'height':1080})
        original=page.url if page.url.startswith('https://syntx.ai/') else 'https://syntx.ai/ru/image/banana'
        try:
            page.goto(CHAT,wait_until='domcontentloaded')
            page.locator('img.bot-image-item__image').wait_for(state='visible',timeout=60000)
            if job['payload']['prompt'] not in page.locator('body').inner_text():raise ValueError('Prompt identity mismatch')
            message=page.locator('.bot-image-message')
            if message.count()!=1:raise ValueError('Ambiguous generated image')
            with page.expect_download(timeout=60000) as event:
                message.locator('[data-cy="download-file-btn"]').evaluate('(button)=>button.click()')
            download=event.value
            suffix=Path(download.suggested_filename).suffix.lower()
            if suffix not in ('.jpg','.jpeg','.png','.webp'):raise ValueError('Unexpected original image format')
            target=ASSETS/(JOB+suffix)
            try:download.save_as(str(target))
            except Exception:
                url=download.url;host=urlsplit(url).netloc
                if not (url.startswith('blob:https://syntx.ai/') or host in ('syntx.ai','r2.syntx.ai','api.syntx.ai')):
                    raise ValueError('Unexpected download origin')
                # Read the actual clicked download through its authenticated browser context.
                data=page.evaluate('''async url=>{const r=await fetch(url);if(!r.ok)throw Error('Download HTTP '+r.status);const b=await r.arrayBuffer();if(b.byteLength>25000000)throw Error('Too large');let s='';const a=new Uint8Array(b);for(let i=0;i<a.length;i+=32768)s+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(s)}''',url)
                target.write_bytes(base64.b64decode(data))
            from PIL import Image
            with Image.open(target) as im:
                width,height=im.size;im.verify()
            if min(width,height)<1000:raise ValueError('Expected original 2K image, not thumbnail')
            result={'file':target.name,'width':width,'height':height,'model':'Banana 2','aspect_ratio':'16:9',
                    'cost_tokens':'3','syntx_chat_url':CHAT,'recovered_existing':True}
            QUEUE.transition(JOB,'uncertain','completed',result=result)
            print(json.dumps(result))
        finally:page.goto(original,wait_until='domcontentloaded')
