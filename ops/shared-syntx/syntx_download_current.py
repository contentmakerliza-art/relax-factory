"""Save exactly the already-clicked SYNTX download; never submit a generation."""
import base64
from urllib.parse import urlsplit


def save_download(page,download,target,maximum=25000000):
    try:
        download.save_as(str(target))
    except Exception:
        url=download.url
        if not (url.startswith('blob:https://syntx.ai/') or urlsplit(url).hostname in ('syntx.ai','api.syntx.ai','r2.syntx.ai')):
            raise ValueError('Unexpected actual download origin')
        data=page.evaluate('''async ({url,maximum})=>{const r=await fetch(url);if(!r.ok)throw Error('Download HTTP '+r.status);const b=await r.arrayBuffer();if(b.byteLength>maximum)throw Error('Too large');let s='';const a=new Uint8Array(b);for(let i=0;i<a.length;i+=32768)s+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(s)}''',{'url':url,'maximum':maximum})
        target.write_bytes(base64.b64decode(data))
    if not 100<target.stat().st_size<=maximum:raise ValueError('Incomplete or oversized actual download')
