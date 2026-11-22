"""Download a recorded native Mountain video through its existing SYNTX chat."""
import argparse,json,re,base64
from pathlib import Path
from browser_lease import browser_lease
from playwright.sync_api import sync_playwright


def main(rid):
    if not re.fullmatch(r'mountain(?:2[2-9]|3[0-5])-native-v[1-9]-20261122',rid):raise ValueError('Unsupported backlog request')
    path=Path('/state')/('runway-'+rid+'.json');record=json.loads(path.read_text())
    if record['state']=='downloaded_needs_qc':return record
    if record['state']!='generated_needs_download':raise ValueError('No confirmed generated result')
    if not record.get('chat_url','').startswith('https://syntx.ai/ru/video/runway/') or not record.get('video_url','').startswith('https://r2.syntx.ai/'):
        raise ValueError('Unexpected recorded result origin')
    with browser_lease():
        with sync_playwright() as p:
            b=p.chromium.connect_over_cdp('http://127.0.0.1:9222',artifacts_dir='/downloads')
            if len(b.contexts)!=1:raise ValueError('Unexpected browser profiles')
            page=b.contexts[0].pages[0] if b.contexts[0].pages else b.contexts[0].new_page()
            original=page.url if page.url.startswith('https://syntx.ai/') else 'https://syntx.ai/ru/video/runway'
            page.set_viewport_size({'width':1920,'height':1080})
            try:
                page.goto(record['chat_url'],wait_until='domcontentloaded')
                page.wait_for_function('url=>[...document.querySelectorAll("video source")].some(e=>e.src===url)',arg=record['video_url'],timeout=60000)
                videos=[v for v in page.locator('video').all() if v.locator('source').get_attribute('src')==record['video_url']]
                if len(videos)!=1:raise ValueError('Ambiguous recorded video')
                message=videos[0].locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," chat-message ")][1]')
                with page.expect_download(timeout=60000) as event:
                    message.locator('[data-cy="download-file-btn"]').evaluate('(button)=>button.click()')
                target=Path('/downloads')/(rid+'.mp4')
                try:event.value.save_as(str(target))
                except Exception:
                    url=event.value.url
                    if not (url.startswith('blob:https://syntx.ai/') or url.startswith('https://r2.syntx.ai/') or url.startswith('https://api.syntx.ai/') or url.startswith('https://syntx.ai/')):
                        raise ValueError('Unexpected actual download origin')
                    data=page.evaluate('''async url=>{const r=await fetch(url);if(!r.ok)throw Error('Download HTTP '+r.status);const b=await r.arrayBuffer();if(b.byteLength>100000000)throw Error('Too large');let s='';const a=new Uint8Array(b);for(let i=0;i<a.length;i+=32768)s+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(s)}''',url)
                    target.write_bytes(base64.b64decode(data))
                    record['retrieval']='actual_download_in_browser_context'
                if target.stat().st_size<10000:raise ValueError('Incomplete existing video')
                record.update(state='downloaded_needs_qc',file=str(target),recovered_existing_result=True)
                path.write_text(json.dumps(record));return record
            finally:page.goto(original,wait_until='domcontentloaded')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');a=p.parse_args()
    print(json.dumps({'state':main(a.request_id)['state']}))
