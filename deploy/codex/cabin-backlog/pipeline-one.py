import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as backlog
"""Run/resume one staged Cabin request on the server. Delivery remains held for QA."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import time
from motion_policy import VERSION, moving_regions


def main(request_id):
    if not backlog.attempt(request_id):
        raise ValueError('Pilot accepts only explicitly staged Cabin attempts')
    folder=Path('/opt/relax-codex/assets')/request_id;folder.mkdir(exist_ok=True)
    lock=(folder/'pipeline.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statefile=folder/'pipeline.json'
    if statefile.exists() and json.loads(statefile.read_text()).get('stage')=='rejected_preview':
        print(json.dumps({'held':'Later full-preview QC rejected this version'}));return
    def save(stage,**details):
        tmp=folder/'pipeline.tmp';tmp.write_text(json.dumps({'request_id':request_id,'stage':stage,
             'updated':time.time(),'motion_policy_version':VERSION,**details},ensure_ascii=False,indent=2));tmp.replace(statefile)
    def execute(script):
        return subprocess.run(['/usr/bin/python3',('/opt/relax-codex/cabin-backlog/' if script in ['production-retry.py', 'pipeline-one.py', 'finish-production.py', 'try-long-segment.py', 'final-preview-review.py', 'deliver-preview.py', 'head-motion.py', 'source-review.py'] else '/opt/relax-codex/')+script,request_id],
            capture_output=True,text=True,check=True,timeout=600)
    ledger=Path('/opt/marketplace-analytics/studio-state')/(('derived-' if '-clean-' in request_id or '-fixed-' in request_id or request_id in ('cabin03-snow-v15-20261121','cabin03-snow2-v15-20261121','cabin03-snow3-v13-20261121','cabin03-snow4-v13-20261121','cabin10-snow-v15-20261121','cabin10-snow2-v15-20261121') else 'runway-')+request_id+'.json')
    if not ledger.exists():
        save('needs_explicit_generation_request');return
    record=json.loads(ledger.read_text())
    if record['state'] in ('qc_rejected','submission_uncertain','submitted'):
        save('held',reason=record['state']);return
    if record['state']!='downloaded_needs_qc':
        save('held',reason='Unexpected generation state');return
    backlog.stage_geometry(request_id,backlog.geometry(request_id))
    # Factory upgrades clear /tmp even when visual QC is already cached.
    subprocess.run(['docker','cp','/opt/marketplace-analytics/studio-downloads/'+request_id+'.mp4',
                    'relax-factory:/tmp/'+request_id+'/source.mp4'],check=True,capture_output=True)
    qcpath=folder/'visual-qc.json'
    try:
        if not qcpath.exists():
            save('checking_frames');execute('server-visual-qc.py')
        qc=json.loads(qcpath.read_text())
        if qc.get('outdoor_snow')=='UNCERTAIN':
            save('held_for_snow_evidence',defects=qc.get('defects',[]));return
        if qc['verdict']=='REJECT':
            save('rejected',defects=qc['defects']);return
        if qc['verdict']!='NEEDS_MOTION_REVIEW':
            raise ValueError('Unknown QC verdict')
        if backlog.attempt(request_id):
            motion_path=folder/'head-motion.json'
            if not motion_path.exists() or 'flank' not in json.loads(motion_path.read_text()):
                save('checking_cat_motion')
                subprocess.run(['docker','cp','/opt/relax-codex/cabin-backlog/head-motion.py','relax-factory:/tmp/head-motion.py'],check=True,capture_output=True)
                result=subprocess.run(['docker','exec','relax-factory','python','/tmp/head-motion.py',request_id],check=True,capture_output=True,text=True,timeout=90)
                motion_path.write_text(json.dumps(json.loads(result.stdout),indent=2))
            motion=json.loads(motion_path.read_text())
            moving=moving_regions(motion)
            if moving:
                # Owner requests visual triage, not rejection from template fit alone.
                (folder/'numeric-motion-flags.json').write_text(json.dumps({'regions':moving,'metrics':motion,'requires_visual_review':True},indent=2))
        preview=folder/'preview.mp4'
        if not preview.exists():
            save('building_preview');execute('server-preview.py')
        # A partial or previously failed render must never be considered completed.
        report=json.loads((folder/'recipe-and-checks.json').read_text())
        if report['technical_check']!='passed':raise ValueError('Technical check missing')
        save('held_for_motion_and_audio_review',preview=str(preview),delivery='NOT_SENT')
    except Exception as exc:
        save('failed_no_auto_retry',error=type(exc).__name__,detail=(getattr(exc,'stderr','') or str(exc))[-3500:])
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
