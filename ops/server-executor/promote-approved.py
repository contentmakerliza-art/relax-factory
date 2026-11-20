"""Host-side idempotent handler. No model calls; only prepared approved manifests."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import time

ROOT=Path('/opt/relax-codex')



def notify(record, receipt):
    if record.get('notification_state') in ('sent','sending','failed'):
        return record
    item=record['publication']
    text=('🗓 Одобрение получено, выпуск в рабочей очереди.\n'
          +item['title']+'\nВыход: '+item['publish_at'].replace('T',' ')+' МСК.\n'
          'Рендер автоматически за 24 часа до выхода, затем Upload-Post. Дополнительно подтверждать не нужно.')
    record['notification_state']='sending'
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    try:
        subprocess.run(['docker','exec','relax-factory','python','-c',
                        'import sys; from render import telegram; telegram.send_text(sys.argv[1])',text],
                       check=True,capture_output=True,text=True,timeout=90)
        record['notification_state']='sent'
    except Exception:
        record['notification_state']='failed'
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    return record


def promote(job_id):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}',job_id):raise ValueError('Invalid job')
    manifest=ROOT/'publication-manifests'/(job_id+'.json')
    if not manifest.exists():return None
    receipts=ROOT/'publication-receipts';receipts.mkdir(mode=0o700,exist_ok=True)
    lock=(receipts/'worker.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    receipt=receipts/(job_id+'.json')
    if receipt.exists():
        prior=json.loads(receipt.read_text())
        if prior.get('state')=='queued':return notify(prior,receipt)
        # An uncertain write is never retried automatically.
        return prior
    config=json.loads(manifest.read_text())
    current=json.loads((Path('/var/lib/relax-factory')/job_id/'job.json').read_text())
    if (current.get('approval') or {}).get('status')!='одобрено':return None
    for source,target in [
        (ROOT/'publish-approved-card.py','/tmp/publish-approved-card.py'),
        (ROOT/'prepare-publication.py','/tmp/prepare-publication.py'),
        (ROOT/'assets/cabin-approved-fireplace-9.wav','/tmp/cabin-full-fireplace-9.wav'),
        (Path(config['cover_path']),'/tmp/codex-cover-'+job_id+'.jpg'),
        (manifest,'/tmp/codex-manifest-'+job_id+'.json')]:
        subprocess.run(['docker','cp',str(source),'relax-factory:'+target],check=True,capture_output=True)
    record={'state':'publication_submission_uncertain','job_id':job_id,'created':time.time()}
    receipt.write_text(json.dumps(record))
    try:
        result=subprocess.run(['docker','exec','relax-factory','python','/tmp/publish-approved-card.py',job_id],
                              capture_output=True,text=True,timeout=210,check=True)
        reply=json.loads(result.stdout);item=reply['publication']
        if item['status'] not in ('ждёт','рендер','проверка','отправлен','на YouTube'):
            raise ValueError('Publication was not activated')
        record.update(state='queued',publication=item,already_queued=reply.get('already_queued'))
        receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2))
        # The existing factory queue handles later render/upload notifications.
        return notify(record,receipt)
    except Exception as error:
        record.update(error=type(error).__name__)
        receipt.write_text(json.dumps(record))
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job_id');print(json.dumps(promote(p.parse_args().job_id),ensure_ascii=False))
