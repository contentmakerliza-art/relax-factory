"""Register one reviewed Paris preview, reserving every external write first.

Run in the factory container. No approval and no final render.
"""
import argparse,base64,hashlib,json,os,shutil,urllib.parse,urllib.request
from pathlib import Path

DATA=Path(os.environ.get('APP_DATA','/app/data'))


def call(path,method='GET',body=None):
    auth=base64.b64encode(('relax:'+os.environ['APP_PASSWORD']).encode()).decode()
    request=urllib.request.Request('http://127.0.0.1:8000'+path,data=body,method=method,
                                  headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)


def register(number):
    rows=json.loads(Path('/tmp/little-paris-dec16-22-manifest.json').read_text())
    row=next(x for x in rows if x['episode']==number)
    assert 32<=number<=38 and row['date']==f'2026-12-{number-16:02d}T22:00'
    source=Path('/tmp')/row['file']
    assert source.stat().st_size==row['bytes'] and hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
    ledger=DATA/f'codex-paris-{number}-20261120.json'
    if ledger.exists():
        print(ledger.read_text());return
    # Refuse an accidental duplicate regardless of the batch ledger.
    for p in DATA.glob('*/job.json'):
        if json.loads(p.read_text()).get('label')==row['label']:
            print(json.dumps({'state':'existing_job_no_resend','job_id':p.parent.name}));return
    ledger.write_text(json.dumps({'state':'creating_uncertain'}))
    job_id=call('/jobs/new','POST',b'')['id']
    ledger.write_text(json.dumps({'state':'uploading','job_id':job_id}))
    offset=0
    with source.open('rb') as f:
        while chunk:=f.read(8*1024*1024):
            call('/jobs/'+job_id+'/files/visual/'+urllib.parse.quote(row['label']+'.mp4')+'?offset='+str(offset),'PUT',chunk)
            offset+=len(chunk)
    call('/jobs/'+job_id+'/import-preview','POST',b'')
    folder=DATA/job_id
    visual=folder/'visual'/'approved-master.mp4'
    os.link(folder/(row['label']+'.mp4'),visual)
    # Preserve whole musical tracks, never the 30-second preview excerpt.
    pool={}
    for parent in (DATA,DATA/'sources'):
        for p in sorted(parent.glob('*/tracks/*.mp3')):
            for name in row['tracks']:
                if p.name==name or p.name.endswith(' — '+name):pool.setdefault(name,p)
    if any(n not in pool for n in row['tracks']):
        ledger.write_text(json.dumps({'state':'held_missing_full_tracks','job_id':job_id}));return
    names=[]
    for i,name in enumerate(row['tracks'],1):
        dst=folder/'tracks'/f'{i:03d} — {name}'
        if not dst.exists():os.link(pool[name],dst)
        names.append(dst.name)
    row.update(job_id=job_id,server_tracks=names)
    (folder/'paris-production-manifest.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
    ledger.write_text(json.dumps({'state':'registered','job_id':job_id,'date':row['date']}))
    print(ledger.read_text())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('episode',type=int);register(p.parse_args().episode)
