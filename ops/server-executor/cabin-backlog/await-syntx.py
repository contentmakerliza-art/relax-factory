"""Wait outside the browser lock, allowing up to two executor slots to overlap."""
import json,subprocess,time,sys
from pathlib import Path
ROOT=Path('/opt/relax-codex');STATE=Path('/opt/marketplace-analytics/studio-state')
def run(script,args):
    code=(ROOT/'cabin-backlog'/script).read_text()
    r=subprocess.run(['docker','exec','-i','-w','/app','marketplace-syntx-studio','python','-',*args],input=code,capture_output=True,text=True,timeout=200)
    if r.returncode:raise RuntimeError(r.stderr[-2500:])
    return json.loads(r.stdout)
def main(kind,request):
    data=json.loads(request.read_text());rid=data['request_id'];ledger=STATE/(('runway-' if kind=='video' else '')+rid+'.json')
    deadline=time.monotonic()+900
    while not ledger.exists() and time.monotonic()<deadline:
        result=run('async-runway-submit.py' if kind=='video' else 'async-banana-submit.py',['--request','/downloads/'+request.name])
        if result.get('busy'):
            for active in result['active']:
                if not active['request_id'].startswith('cabin'):raise ValueError('Unexpected active request')
                try:run('async-syntx-poll.py',[active['kind'],active['request_id']])
                except (subprocess.SubprocessError,RuntimeError):pass
            time.sleep(3)
        elif not ledger.exists():raise RuntimeError('Submission unconfirmed; no duplicate allowed')
    if not ledger.exists():raise TimeoutError('Two provider slots require inspection')
    while time.monotonic()<deadline:
        record=json.loads(ledger.read_text())
        if record['state']=='downloaded_needs_qc':return
        if record['state']=='generation_failed':raise RuntimeError('Confirmed SYNTX technical failure')
        if record['state'] not in ('submitted','generated_needs_download') or not record.get('async_submission'):raise RuntimeError('Inspect existing submission; never repeat it')
        try:run('async-syntx-poll.py',[kind,rid])
        except (subprocess.SubprocessError,RuntimeError) as error:
            # Retrieval trouble cannot trigger another generation. Bounded resume.
            folder=ROOT/'cabin-backlog/poll-errors';folder.mkdir(exist_ok=True)
            (folder/(rid+'.txt')).write_text(str(error)[-2500:])
        time.sleep(8)
    raise TimeoutError('Existing result requires inspection, not regeneration')
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
