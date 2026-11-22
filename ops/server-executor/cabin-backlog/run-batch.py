"""Fair Cabin rounds, two provider generations, one heavy QA/render slot.

Short UI operations use the shared browser lease; provider waits run outside it.
Exact ledgers prevent duplicate paid submissions. A rejected room yields its turn.
"""
import concurrent.futures,fcntl,json,subprocess,time,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as registry
ROOT=Path('/opt/relax-codex');BASE=ROOT/'cabin-backlog'
DONE={'sent_for_owner_approval','already_in_publication_queue'}
RETRY={'deferred_after_video_rejection','deferred_after_preview_rejection',
       'preparation_failed_no_submission','recover_existing_video','recover_existing_image'}
OUTAGE={'model_unavailable_no_retry','provider_unavailable_no_image_purchase'}

def read(path):return json.loads(path.read_text()) if path.exists() else {}

def run_group(row,stop):
    group=row['request_group'];folder=ROOT/'production-runs'/group;folder.mkdir(exist_ok=True,parents=True)
    queue=read(Path('/var/lib/relax-factory/queue/queue.json'))
    covered=[x for x in queue if x.get('channel')=='Quiet Pines Cabin' and x.get('publish_at')==row['publish_at'] and x.get('status') not in ('отменено','ошибка')]
    if covered:return {'stage':'already_in_publication_queue','queue_ids':[x['id'] for x in covered]}
    delivered=read(folder/'delivery.json')
    if delivered.get('stage')=='sent_for_owner_approval':return delivered
    if stop.is_set():return {'stage':'waiting_for_provider_recovery'}
    try:
        result=subprocess.run(['/usr/bin/python3',str(BASE/'production-retry.py'),str(ROOT/'production-configs'/(group+'.json'))],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=5400)
        (folder/'producer-last-output.log').write_text((result.stdout+result.stderr)[-12000:])
        if result.returncode:raise RuntimeError('Producer exited '+str(result.returncode))
        state=read(folder/'state.json')
        if state.get('stage')=='assembly_repair_required':
            rid=state['request_id'];recipe=read(ROOT/'assets'/rid/'recipe-and-checks.json')
            from cabin_loop_recipe import VERSION as LOOP_VERSION
            if recipe.get('builder_version')==LOOP_VERSION or '-fixed-' in rid:
                return dict(stage='assembly_repair_requires_review',request_id=rid,
                            reason='Already uses repaired loop recipe; do not repeat or regenerate')
            result=subprocess.run(['/usr/bin/python3',str(ROOT/'repair-saved-cabin.py'),rid],
                stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=1800)
            (folder/'assembly-repair-output.log').write_text((result.stdout+result.stderr)[-9000:])
            if result.returncode:raise RuntimeError('Assembly repair needs inspection')
            return read(folder/'delivery.json')
        if state.get('stage') in OUTAGE:stop.set()
        if state.get('stage')!='preview_ready_for_final_checks':return state
        result=subprocess.run(['/usr/bin/python3',str(BASE/'finish-production.py'),group],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=1800)
        (folder/'finisher-last-output.log').write_text((result.stdout+result.stderr)[-12000:])
        if result.returncode:raise RuntimeError('Finisher exited '+str(result.returncode))
        return read(folder/'delivery.json')
    except Exception as error:
        return {'stage':'needs_attention','error':str(error),'production':read(folder/'state.json')}

def main():
    lock=(BASE/'batch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    path=BASE/'batch-status.json';status=read(path);status.setdefault('scenes',{})
    status.update(state='running',execution='two_provider_slots_one_media_slot',worker_count=2,updated=time.time())
    def save():
        status['updated']=time.time();temp=path.with_suffix('.tmp');temp.write_text(json.dumps(status,ensure_ascii=False,indent=2));temp.replace(path)
    rows=registry.records()
    # Give two untouched rooms their first opportunity before another attempt at room 03.
    rows=sorted(rows,key=lambda r:(r['request_group'].startswith('cabin03-'),r['publish_at']))
    stop=threading.Event()
    for round_number in range(1,10):
        pending=[r for r in rows if status['scenes'].get(r['request_group'],{}).get('stage') not in DONE
            and (round_number==1 or status['scenes'].get(r['request_group'],{}).get('stage') in RETRY)]
        if not pending:break
        status.update(round=round_number,round_pending=[r['request_group'] for r in pending]);save()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures={executor.submit(run_group,row,stop):row for row in pending}
            for future in concurrent.futures.as_completed(futures):
                row=futures[future];result=future.result();status['scenes'][row['request_group']]=result
                status['round_pending'].remove(row['request_group']);save()
        if stop.is_set():status.update(state='held_for_provider_recovery');save();return
    stages=[v.get('stage') for v in status['scenes'].values()]
    status['state']='all_previews_sent' if len(stages)==len(rows) and all(s in DONE for s in stages) else 'pass_completed_with_holds'
    save()

if __name__=='__main__':main()
