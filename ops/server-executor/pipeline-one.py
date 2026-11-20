"""Run/resume one staged Cabin request on the server. Delivery remains held for QA."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import time


def main(request_id):
    if not re.fullmatch('cabin(?:08|17|18|22)-fullframe-v[1-3]-20261120',request_id):
        raise ValueError('Pilot accepts only bounded Cabin 17/18 attempts')
    folder=Path('/opt/relax-codex/assets')/request_id;folder.mkdir(exist_ok=True)
    lock=(folder/'pipeline.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statefile=folder/'pipeline.json'
    def save(stage,**details):
        tmp=folder/'pipeline.tmp';tmp.write_text(json.dumps({'request_id':request_id,'stage':stage,
             'updated':time.time(),**details},ensure_ascii=False,indent=2));tmp.replace(statefile)
    def execute(script):
        return subprocess.run(['/usr/bin/python3','/opt/relax-codex/'+script,request_id],
            capture_output=True,text=True,check=True,timeout=600)
    ledger=Path('/opt/marketplace-analytics/studio-state')/('runway-'+request_id+'.json')
    if not ledger.exists():
        save('needs_explicit_generation_request');return
    record=json.loads(ledger.read_text())
    if record['state'] in ('qc_rejected','submission_uncertain','submitted'):
        save('held',reason=record['state']);return
    if record['state']!='downloaded_needs_qc':
        save('held',reason='Unexpected generation state');return
    qcpath=folder/'visual-qc.json'
    try:
        if not qcpath.exists():
            save('checking_frames');execute('server-visual-qc.py')
        qc=json.loads(qcpath.read_text())
        if qc['verdict']=='REJECT':
            save('rejected',defects=qc['defects']);return
        if qc['verdict']!='NEEDS_MOTION_REVIEW':
            raise ValueError('Unknown QC verdict')
        if request_id.startswith(('cabin08-','cabin18-','cabin22-')):
            motion_path=folder/'head-motion.json'
            if not motion_path.exists() or 'flank' not in json.loads(motion_path.read_text()):
                save('checking_cat_motion')
                subprocess.run(['docker','cp','/opt/relax-codex/head-motion.py','relax-factory:/tmp/head-motion.py'],check=True,capture_output=True)
                result=subprocess.run(['docker','exec','relax-factory','python','/tmp/head-motion.py',request_id],check=True,capture_output=True,text=True,timeout=90)
                motion_path.write_text(json.dumps(json.loads(result.stdout),indent=2))
            motion=json.loads(motion_path.read_text())
            moving=[name for name in ('head','paws','wall','flank') if max(motion[name]['x_range_pixels'],motion[name]['y_range_pixels'])>1.0]
            if moving:
                save('rejected_motion',moving_regions=moving,metrics=motion);return
        preview=folder/'preview.mp4'
        if not preview.exists():
            save('building_preview');execute('server-preview.py')
        # A partial or previously failed render must never be considered completed.
        report=json.loads((folder/'recipe-and-checks.json').read_text())
        if report['technical_check']!='passed':raise ValueError('Technical check missing')
        save('held_for_motion_and_audio_review',preview=str(preview),delivery='NOT_SENT')
    except Exception as exc:
        save('failed_no_auto_retry',error=type(exc).__name__)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
