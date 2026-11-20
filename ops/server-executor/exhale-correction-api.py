"""Register a checked corrected Exhale preview and deliver it exactly once."""
import argparse,base64,hashlib,json,os,re,time,urllib.parse,urllib.request
from pathlib import Path

DATA=Path(os.environ.get('APP_DATA','/data'))


def call(path,method='GET',body=None):
    auth=base64.b64encode(('relax:'+os.environ['APP_PASSWORD']).encode()).decode()
    req=urllib.request.Request('http://127.0.0.1:8000'+path,data=body,method=method,
                              headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)


def plan_approved(job_id):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}',job_id):raise ValueError('Invalid job')
    folder=DATA/job_id
    recipe=json.loads((folder/'portable-correction.json').read_text())
    meta=json.loads((folder/'job.json').read_text())
    if (meta.get('approval') or {}).get('status')!='одобрено':return None
    response=call('/production')
    rows=response if isinstance(response,list) else response.get('items',response.get('rows',[]))
    row=next((r for r in rows if r.get('source')==job_id),None)
    if not row:raise ValueError('Approved correction missing from intake')
    if row.get('publish_at')==recipe['publish_at'] and row.get('profile')=='Exhale_to_Sleep' and row.get('hours')==10:
        return row
    values=dict(channel='Exhale to Sleep',publish_at=recipe['publish_at'],hours=10,
        profile='Exhale_to_Sleep',title=row.get('title',''),description=row.get('description',''),tags=row.get('tags',''))
    return call('/production/'+job_id+'/plan','POST',urllib.parse.urlencode(values).encode())


def main(task_id):
    if not re.fullmatch('[a-f0-9]{64}',task_id):raise ValueError('Invalid correction identity')
    folder=DATA/'sources/executor-library/corrections'/task_id
    request=json.loads((folder/'request.json').read_text())
    report=json.loads((folder/'render-report.json').read_text())
    ledger=folder/'telegram-delivery.json'
    if ledger.exists():return json.loads(ledger.read_text())
    def current():
        meta=json.loads((DATA/request['source_job']/'job.json').read_text());ap=meta.get('approval') or {}
        decision=dict(job_id=request['source_job'],status=ap.get('status'),time=ap.get('time'),
            comments=[{k:c[k] for k in ('time','text','transcript','voice') if k in c}
                      for c in ap.get('comments',[]) if isinstance(c,dict)])
        return decision['status']=='правка' and hashlib.sha256(json.dumps(decision,
            sort_keys=True,ensure_ascii=False).encode()).hexdigest()==task_id
    if not current():return {'stage':'superseded'}
    source=Path(report['preview']).resolve()
    if source.parent!=folder.resolve() or report['frames']!=900 or report['seconds']!=30:
        raise ValueError('Invalid checked render')
    if report['background_adjustment_db']!=request['background_db']:
        raise ValueError('Rendered adjustment differs from owner request')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=report['sha256']:raise ValueError('Render changed')
    label=request['label'].removesuffix(' — 30 секунд')+f" — фон тише на {-request['background_db']:g} дБ — 30 секунд"
    if len(label)>180:raise ValueError('Label too long')
    ledger.write_text(json.dumps({'stage':'registration_uncertain'}))
    job_id=call('/jobs/new','POST',b'')['id']
    ledger.write_text(json.dumps({'stage':'uploading','job_id':job_id}))
    offset=0
    with source.open('rb') as f:
        while chunk:=f.read(8*1024*1024):
            call('/jobs/'+job_id+'/files/visual/'+urllib.parse.quote(label+'.mp4')+'?offset='+str(offset),'PUT',chunk)
            offset+=len(chunk)
    call('/jobs/'+job_id+'/import-preview','POST',b'')
    recipe=dict(parent_job=request['source_job'],recipe_job_id=request['recipe_job_id'],
        number=request['number'],background_db=request['background_db'],publish_at=request['publish_at'],
        task_id=task_id,full_sources_preserved=True,long_final_adapter_required=True)
    (DATA/job_id/'portable-correction.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2))
    if not current():
        value=dict(stage='superseded_before_send',job_id=job_id);ledger.write_text(json.dumps(value));return value
    ledger.write_text(json.dumps({'stage':'telegram_submission_uncertain','job_id':job_id}))
    call('/jobs/'+job_id+'/telegram','POST',b'')
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        meta=json.loads((DATA/job_id/'job.json').read_text());tg=meta.get('telegram') or {}
        if tg.get('status')=='отправлено':
            value=dict(stage='sent',job_id=job_id,parent_job=request['source_job'],publish_at=request['publish_at'])
            ledger.write_text(json.dumps(value,ensure_ascii=False,indent=2));return value
        if tg.get('status')=='ошибка':raise ValueError('Telegram error; inspect before retry')
        time.sleep(3)
    raise TimeoutError('Telegram outcome uncertain; never resend blindly')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('task_id',nargs='?');p.add_argument('--plan-approved')
    a=p.parse_args();print(json.dumps(plan_approved(a.plan_approved) if a.plan_approved else main(a.task_id),ensure_ascii=False))
