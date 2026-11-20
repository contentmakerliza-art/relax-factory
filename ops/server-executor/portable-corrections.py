"""Execute explicitly supported owner audio corrections; no model calls."""
import argparse,fcntl,hashlib,importlib.util,json,os,re,sqlite3,subprocess,time
from pathlib import Path

ROOT=Path('/opt/relax-codex')
DATA=Path('/var/lib/relax-factory')
LIB=DATA/'sources/executor-library'
DATABASE='/var/lib/relax-codex-bridge/tasks.sqlite'


def parse_reduction(text):
    match=re.fullmatch(r'\s*(?:сделай(?:те)?\s+)?фон\s+(?:тише|потише)\s+на\s+(\d+(?:[.,]\d+)?)\s*(?:дб|db)\s*[.!]?\s*',text.casefold())
    if not match:return None
    value=float(match[1].replace(',','.'))
    return -value if .5<=value<=12 else None


def read(path):return json.loads(path.read_text()) if path.exists() else None


def bridge():
    spec=importlib.util.spec_from_file_location('portable_bridge',ROOT/'approval-bridge.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def fingerprint(row):
    return hashlib.sha256(json.dumps({k:row[k] for k in ('job_id','status','time','comments')},
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def recipe_for(job_id):
    inherited=read(DATA/job_id/'portable-correction.json')
    original=inherited.get('recipe_job_id') if inherited else job_id
    rows=read(LIB/'assets/Исходники/Exhale to Sleep/Новые 20 проб/Журнал производства.json') or []
    matches=[r for r in rows if r.get('telegram_job_id')==original]
    if len(matches)!=1:return None
    return matches[0],float((inherited or {}).get('background_db',0)),original


def reconcile_approval(job_id):
    if not (DATA/job_id/'portable-correction.json').exists():return None
    result=subprocess.run(['docker','exec','relax-factory','python',
        '/data/sources/executor-library/tools/exhale-correction-api.py','--plan-approved',job_id],
        check=True,capture_output=True,text=True,timeout=90)
    return json.loads(result.stdout)


def try_dispatch(task_id,row,db):
    if row.get('archived') or row.get('status')!='правка' or 'Exhale to Sleep' not in row.get('label',''):return False
    comments=row.get('comments') or []
    if not comments:return False
    delta=parse_reduction(comments[-1].get('text') or comments[-1].get('transcript') or '')
    if delta is None:return False
    recipe=recipe_for(row['job_id'])
    if not recipe:return False
    item,previous,original=recipe
    total=previous+delta
    if total< -24:return False
    # Do not touch a version already scheduled or uploaded; a replacement route
    # must first pause its publication explicitly.
    queue=read(DATA/'queue/queue.json') or []
    if any(q.get('source')==row['job_id'] for q in queue):return False
    if not re.fullmatch('[a-f0-9]{64}',task_id) or fingerprint(row)!=task_id:raise ValueError('Bad task identity')
    folder=LIB/'corrections'/task_id;folder.mkdir(parents=True,exist_ok=True)
    request=folder/'request.json'
    if request.exists():
        with db:db.execute("UPDATE tasks SET state='portable_existing_request_attention' WHERE id=?",(task_id,))
        return True
    value=dict(task_id=task_id,source_job=row['job_id'],recipe_job_id=original,
        number=item['number'],publish_at=item['date']+'T22:00',background_db=total,
        delta_db=delta,label=item['label'],created=time.time(),stage='dispatching')
    with request.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    with db:db.execute("UPDATE tasks SET state='portable_dispatching' WHERE id=?",(task_id,))
    try:
        subprocess.run(['systemd-run','--unit=relax-audio-fix-'+task_id[:16],'--collect',
            '-p','MemoryMax=128M','-p','CPUQuota=10%','-p','RuntimeMaxSec=1200',
            '/usr/bin/python3',str(ROOT/'portable-corrections.py'),'--run',task_id],
            check=True,capture_output=True,text=True,timeout=30)
    except Exception:
        with db:db.execute("UPDATE tasks SET state='portable_dispatch_uncertain' WHERE id=?",(task_id,))
        raise
    return True


def run_task(task_id):
    if not re.fullmatch('[a-f0-9]{64}',task_id):raise ValueError('Bad task')
    folder=LIB/'corrections'/task_id;request=read(folder/'request.json')
    with (LIB/'corrections/worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        receipt=folder/'execution.json'
        if receipt.exists():return
        def save(stage,**extra):
            receipt.write_text(json.dumps(dict(stage=stage,updated=time.time(),**extra),ensure_ascii=False,indent=2))
            with sqlite3.connect(DATABASE,timeout=10) as db:
                db.execute('UPDATE tasks SET state=? WHERE id=?',('portable_'+stage,task_id))
        def current():
            row=bridge().read_rows(DATA).get(request['source_job'])
            return row and row['status']=='правка' and fingerprint(row)==task_id
        if not current():save('superseded');return
        save('rendering')
        try:
            tool=LIB/'tools/exhale-portable.py'
            image=subprocess.check_output(['docker','inspect','--format','{{.Image}}','relax-factory'],text=True).strip()
            prefix='/data/sources/executor-library'
            output=prefix+'/corrections/'+task_id
            args=['docker','run','--rm','--name','relax-audio-fix-'+task_id[:12],
                '--memory','512m','--cpus','1','--network','none','--volumes-from','relax-factory',
                '--env','PYTHONPATH='+prefix+'/runtime/python3.12','--entrypoint','python',image,
                prefix+'/tools/exhale-portable.py','--assets',prefix+'/assets','--output',output,
                '--number',str(request['number']),'--background-db',str(request['background_db'])]
            result=subprocess.run(args,check=True,capture_output=True,text=True,timeout=900)
            report=json.loads(result.stdout)
            (folder/'render-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            if not current():save('superseded');return
            # Persist BEFORE registration/send. Unknown outcomes never resend.
            save('delivery_started',render=report)
            x=subprocess.run(['docker','exec','relax-factory','python',prefix+'/tools/exhale-correction-api.py',task_id],
                             check=True,capture_output=True,text=True,timeout=240)
            reply=json.loads(x.stdout)
            save('sent' if reply['stage']=='sent' else 'delivery_attention',delivery=reply,render=report)
        except Exception as error:
            save('failed_no_auto_retry',error=type(error).__name__)
            marker=folder/'failure-notification.json'
            if not marker.exists():
                marker.write_text(json.dumps({'state':'sending'}))
                try:
                    subprocess.run(['docker','exec','relax-factory','python','-c',
                        'from render import telegram; telegram.send_text("Правка Exhale сохранена, но серверная пересборка остановилась. Исходники сохранены; нужна проверка координатора.")'],
                        check=True,capture_output=True,text=True,timeout=60)
                    marker.write_text(json.dumps({'state':'sent'}))
                except Exception:marker.write_text(json.dumps({'state':'unconfirmed_no_retry'}))
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);run_task(p.parse_args().run)
