"""Attach the verified full sources to 23 already approved previews.

The original MP4 and owner decisions remain unchanged. Restart the idle factory
after this one-time migration so in-memory source objects are hydrated.
"""
import hashlib,json,os,shutil,time
from pathlib import Path

DATA=Path('/var/lib/relax-factory');LIB=DATA/'sources/executor-library';STAGE=LIB/'exhale-publication-staging'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    quality=json.loads((LIB/'tests/preserved-exhale/quality-report.json').read_text())
    handoff=json.loads((LIB/'tests/preserved-exhale/handoff-quality.json').read_text())
    if not quality.get('passed') or quality.get('recipes_checked')!=23 or not handoff.get('passed'):
        raise ValueError('Both real media checks must pass first')
    rows=json.loads((STAGE/'manifest.json').read_text());actions=[]
    for row in rows:
        folder=DATA/row['job_id'];meta=json.loads((folder/'job.json').read_text());output=folder/meta['output']
        if meta['approval']['status']!='одобрено' or sha(output)!=row['preview_sha256']:raise ValueError('Approval changed')
        staged=STAGE/row['job_id']
        for kind in ['voice','ambient']:
            expected={p.name for p in (staged/kind).iterdir()}
            if any(p.name not in expected for p in (folder/kind).iterdir()):raise ValueError('Unexpected existing source files')
            for p in (staged/kind).iterdir():
                dst=folder/kind/p.name
                if dst.exists() and sha(dst)!=sha(p):raise ValueError('Existing source differs')
        actions.append((row,folder,meta,output,staged))
    for row,folder,meta,output,staged in actions:
        backup=staged/'job-before-full-source-activation.json'
        if not backup.exists():shutil.copy2(folder/'job.json',backup)
        approved=staged/'approved-preview.mp4'
        if not approved.exists():os.link(output,approved)
        elif sha(approved)!=row['preview_sha256']:raise ValueError('Protected preview differs')
        for kind in ['voice','ambient']:
            for p in (staged/kind).iterdir():
                dst=folder/kind/p.name
                if not dst.exists():
                    if p.suffix=='.json':shutil.copy2(p,dst)
                    else:os.link(p,dst)
        shutil.copy2(staged/'breath.json',folder/'breath.json')
        meta['settings'].update(width=1920,height=1080,fps=30,duration=30,
            stabilize=False,smooth=False,loop_mode='none',loop_crossfade=0,find_loop_point=False,
            speed=1,logo='',audio_bitrate='320k')
        temp=folder/'job.exhale-activation.tmp';temp.write_text(json.dumps(meta,ensure_ascii=False));temp.replace(folder/'job.json')
        archive=DATA/'sources'/row['job_id'];archive.mkdir(exist_ok=True)
        for kind in ['voice','ambient']:
            (archive/kind).mkdir(exist_ok=True)
            for p in (folder/kind).iterdir():
                dst=archive/kind/p.name
                if not dst.exists():
                    if p.suffix=='.json':shutil.copy2(p,dst)
                    else:os.link(p,dst)
        shutil.copy2(folder/'breath.json',archive/'breath.json')
        shutil.copy2(folder/'job.json',archive/'settings.json')
        record=dict(activated=True,job_id=row['job_id'],preview_sha256=sha(output),
            owner_approval_unchanged=meta['approval']==json.loads(backup.read_text())['approval'],
            full_voice_seconds=row['voice_seconds'],created=time.time(),new_generations=0)
        (staged/'activation-receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
        print(json.dumps(record,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
