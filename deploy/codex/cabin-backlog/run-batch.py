"""Serial, durable Cabin backlog runner. Runs independently of a MacBook.

Only exact registry entries; checked previews go to owner, never self-approved.
Uncertain submissions or deliveries are held, not repeated.
"""
import fcntl,json,subprocess,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as registry
ROOT=Path('/opt/relax-codex');BASE=ROOT/'cabin-backlog'

def read(path):return json.loads(path.read_text()) if path.exists() else {}

def main():
    lock=(BASE/'batch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statusfile=BASE/'batch-status.json';status=read(statusfile)
    status.update(started=status.get('started',time.time()),state='running',updated=time.time())
    status.setdefault('scenes',{})
    def save():
        status['updated']=time.time();tmp=statusfile.with_suffix('.tmp');tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2));tmp.replace(statusfile)
    save()
    for row in registry.records():
        group=row['request_group'];folder=ROOT/'production-runs'/group;folder.mkdir(exist_ok=True,parents=True)
        queue=read(Path('/var/lib/relax-factory/queue/queue.json'))
        covered=[x for x in queue if x.get('channel')=='Quiet Pines Cabin'
            and x.get('publish_at')==row['publish_at'] and x.get('status') not in ('отменено','ошибка')]
        if covered:
            status['scenes'][group]={'state':'already_in_publication_queue','queue_ids':[x['id'] for x in covered]};save();continue
        delivered=read(folder/'delivery.json')
        if delivered.get('stage')=='sent_for_owner_approval':
            status['scenes'][group]=delivered;save();continue
        status['current_group']=group;status['scenes'][group]={'state':'processing','date':row['publish_at']};save()
        try:
            # A resume may already have a checked preview. Never regenerate it.
            command=['/usr/bin/python3',str(BASE/'production-retry.py'),str(ROOT/'production-configs'/(group+'.json'))]
            result=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=14400)
            (folder/'producer-last-output.log').write_text((result.stdout+result.stderr)[-12000:])
            if result.returncode:raise RuntimeError('Producer exited '+str(result.returncode))
            produced=read(folder/'state.json')
            if produced.get('stage')=='preview_ready_for_final_checks':
                result=subprocess.run(['/usr/bin/python3',str(BASE/'finish-production.py'),group],
                    stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=11000)
                (folder/'finisher-last-output.log').write_text((result.stdout+result.stderr)[-12000:])
                if result.returncode:raise RuntimeError('Finisher exited '+str(result.returncode))
                status['scenes'][group]=read(folder/'delivery.json')
            else:status['scenes'][group]=produced
        except Exception as error:
            status['scenes'][group]={'state':'needs_attention','error':str(error),'production':read(folder/'state.json')}
        save()
        # A provider outage affects every room: don't create 12 failures or paid images.
        produced=read(folder/'state.json')
        if produced.get('stage') in ('model_unavailable_no_retry','provider_unavailable_no_image_purchase','recover_existing_video'):
            status.update(state='held_for_service_or_uncertain_submission',blocking_group=group);save();return
    status['state']='batch_pass_completed';save()

if __name__=='__main__':main()
