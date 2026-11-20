"""Try an 8+ second stationary full-frame segment before regenerating.

Never modifies the rejected parent. Derived clips receive their own QC.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path('/opt/relax-codex')
DOWNLOADS=Path('/opt/marketplace-analytics/studio-downloads')


def run(args,timeout=900):
    return subprocess.run(args,check=True,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,timeout=timeout)


def main(request_id):
    if not re.fullmatch(r'cabin(?:08|22)-fullframe-v[1-9]-20261120',request_id):
        raise ValueError('Unsupported parent')
    parent=ROOT/'assets'/request_id
    report=parent/'long-segment.json'
    if report.exists():
        cached=json.loads(report.read_text())
        if cached.get('state')=='preview_ready':
            current=json.loads((ROOT/'assets'/cached['request_id']/'pipeline.json').read_text())
            if current['stage']!='held_for_motion_and_audio_review':
                return dict(state='trim_rejected_after_final_review',pipeline=current)
        return cached
    def save(**data):
        report.write_text(json.dumps(data,ensure_ascii=False,indent=2));return data
    source=DOWNLOADS/(request_id+'.mp4')
    if not source.is_file():return save(state='no_downloaded_parent')
    prefix='/tmp/'+request_id
    run(['docker','exec','relax-factory','mkdir','-p',prefix])
    run(['docker','cp',str(source),'relax-factory:'+prefix+'/source.mp4'])
    run(['docker','cp',str(ROOT/'head-motion.py'),'relax-factory:/tmp/head-motion.py'])
    run(['docker','exec','relax-factory','python','/tmp/head-motion.py',request_id],timeout=120)
    traces=json.loads(run(['docker','exec','relax-factory','cat',prefix+'/motion-traces.json']).stdout)
    regions=traces['positions'];rate=traces['sample_rate'];n=len(regions['head']);best=None
    for start in range(n):
        for end in range(start+8*rate,n+1):
            # A match pinned against the search boundary can falsely look still.
            if any(abs(v[0])>=2.75 or abs(v[1])>=2.75 or v[2]>1000
                   for values in regions.values() for v in values[start:end]):continue
            drift=max(max(v[i] for v in values[start:end])-min(v[i] for v in values[start:end])
                      for values in regions.values() for i in (0,1))
            if drift<=1 and (best is None or end-start>best[1]-best[0]):best=(start,end)
    if best is None:return save(state='no_clean_eight_second_segment')
    start,end=best
    if end-start>n-rate/2:return save(state='no_localized_motion_defect_to_trim')
    derived=request_id.replace('-fullframe-','-clean-')
    target=DOWNLOADS/(derived+'.mp4')
    work='/tmp/'+derived
    run(['docker','exec','relax-factory','mkdir','-p',work])
    run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-n','-threads','1',
         '-ss',str(start/rate),'-i',prefix+'/source.mp4','-t',str((end-start)/rate),
         '-an','-c:v','libx264','-threads','2','-preset','fast','-crf','17',work+'/source.mp4'])
    run(['docker','cp','relax-factory:'+work+'/source.mp4',str(target)])
    ledger=Path('/opt/marketplace-analytics/studio-state')/('derived-'+derived+'.json')
    with ledger.open('x') as f:json.dump(dict(state='downloaded_needs_qc',kind='full_frame_temporal_trim',
        request_id=derived,parent_request_id=request_id,start_seconds=start/rate,
        end_seconds=end/rate,parent_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        local_masks=False,cost_tokens=0),f)
    run(['/usr/bin/python3',str(ROOT/'pipeline-one.py'),derived])
    checked=json.loads((ROOT/'assets'/derived/'pipeline.json').read_text())
    if checked['stage']=='held_for_motion_and_audio_review':
        return save(state='preview_ready',request_id=derived,preview=checked['preview'])
    return save(state='trim_rejected',derived_request_id=derived,pipeline=checked)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id')
    print(json.dumps(main(p.parse_args().request_id),ensure_ascii=False))
