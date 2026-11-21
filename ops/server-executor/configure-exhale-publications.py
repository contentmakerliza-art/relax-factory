"""Fill 23 approved Exhale cards; only the factory callback creates queue items."""
import base64,hashlib,json,os,subprocess,urllib.parse,urllib.request,uuid
from pathlib import Path

DATA=Path(os.environ.get('APP_DATA','/data'));STAGE=DATA/'sources/executor-library/exhale-publication-staging'

def call(path,method='GET',values=None,file=None):
    headers={'Authorization':'Basic '+base64.b64encode(('relax:'+os.environ['APP_PASSWORD']).encode()).decode()}
    body=None
    if file:
        key,p,mime=file;boundary=uuid.uuid4().hex
        body=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{p.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+p.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        headers['Content-Type']='multipart/form-data; boundary='+boundary
    elif values is not None:
        body=urllib.parse.urlencode(values).encode();headers['Content-Type']='application/x-www-form-urlencoded'
    request=urllib.request.Request('http://127.0.0.1:8000'+path,data=body,method=method,headers=headers)
    with urllib.request.urlopen(request,timeout=120) as r:return json.load(r)

def main():
    rows=json.loads((STAGE/'manifest.json').read_text())
    backgrounds=dict(ocean='Ocean Waves',forest='Night Forest',brown='Brown Noise',rain='Rain',pink='Pink Noise')
    names={'Calm 4-6':'Calm 4-6 Breathing','Vagus 4-8':'Slow 4-8 Breathing',
           '3am 4-7-8':'4-7-8 Breathing','Overthinking':'Double Sighs & Slow Breathing'}
    for row in rows:
        jid=row['job_id'];folder=DATA/jid;staged=STAGE/jid;ledger=staged/'publication-receipt.json'
        meta=json.loads((folder/'job.json').read_text());preview=folder/meta['output']
        if meta['approval']['status']!='одобрено' or hashlib.sha256(preview.read_bytes()).hexdigest()!=row['preview_sha256']:
            raise ValueError('Exact owner-approved preview changed')
        queue=call('/queue');existing=[r for r in queue if r.get('source')==jid]
        if len(existing)>1:raise ValueError('Duplicate source; inspect without creating anything')
        if existing and existing[0]['publish_at']!=row['publish_at']:raise ValueError('Existing queue date differs')
        if ledger.exists() and json.loads(ledger.read_text()).get('state')=='queued':
            if not existing:raise ValueError('Previously queued item disappeared')
            print(json.dumps(dict(already_queued=jid,date=row['publish_at'])),flush=True);continue
        if any(r.get('user')=='Exhale_to_Sleep' and r.get('publish_at','')[:10]==row['publish_at'][:10]
               and r.get('source')!=jid for r in queue):raise ValueError('Reserved date is occupied')
        title=f"{names[row['mode']]} & {backgrounds[row['background']]} | Black Screen | 10 Hours"
        description=(f"A short guided breathing practice with {backgrounds[row['background']].lower()}, followed by a black screen and continuous background sound.\n\n"
            'The breathing circle fades gently after the introduction. No more talking after the opening practice.\n\n'
            'Ten hours for relaxing, resting and winding down.\n\nExhale to Sleep.')
        tags='guided breathing, black screen, sleep sounds, '+row['background']+', relaxation, exhale to sleep'
        if len(title)>100:raise ValueError('Title exceeds limit')
        if not existing:
            call('/production/'+jid+'/plan','POST',dict(channel='Exhale to Sleep',publish_at=row['publish_at'],
                title=title,description=description,tags=tags,profile='Exhale_to_Sleep',hours='10'))
        # Planning synchronously queues a ready source. A second POST /queue is forbidden.
        existing=[r for r in call('/queue') if r.get('source')==jid]
        if len(existing)!=1:raise ValueError('Automatic queue creation requires inspection')
        item=existing[0]
        if item['hours']!=10 or item['publish_at']!=row['publish_at'] or item['status']!='ждёт' or item.get('job'):
            raise ValueError('Unexpected publication state')
        item=call('/queue/'+item['id'],'POST',dict(title=item['title'],description=item.get('description',''),
            tags=', '.join(item.get('tags',[])),publish_at=item['publish_at'],user='Exhale_to_Sleep',
            synthetic='true',logo='false',render_now='false'))
        cover=folder/'cover.jpg'
        if not item.get('cover'):
            if not cover.exists():
                subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss','18','-i',str(preview),
                    '-frames:v','1','-threads','1',str(cover)],check=True,capture_output=True,timeout=60)
            call('/queue/'+item['id']+'/cover','POST',file=('cover_file',cover,'image/jpeg'))
        final=next(r for r in call('/queue') if r['id']==item['id'])
        if final.get('logo') or final.get('render_now') or not final.get('cover') or not final.get('synthetic'):
            raise ValueError('Publication settings not saved')
        record=dict(state='queued',job_id=jid,publication=final,preview_unchanged=True,full_voice_preserved=True)
        ledger.write_text(json.dumps(record,ensure_ascii=False,indent=2))
        print(json.dumps(dict(queued=jid,date=row['publish_at'],publication_id=final['id'])),flush=True)

if __name__=='__main__':main()
