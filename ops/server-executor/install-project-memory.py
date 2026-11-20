"""Install prepared memory modules with backups, context checks and rollback."""
import hashlib,importlib.util,json,py_compile,shutil,subprocess,sys,time
from pathlib import Path

ROOT=Path('/opt/relax-codex');STAGE=ROOT/'staging/memory-20261121'
NAMES=['project_memory.py','plan-one.py','dispatch-decisions.py','source-review.py',
       'server-visual-qc.py','final-preview-review.py']


def service(*args):
    return subprocess.run(['systemctl',*args],check=True,capture_output=True,text=True,timeout=30)


def main():
    for name in NAMES:py_compile.compile(str(STAGE/name),doraise=True)
    policy=json.loads((STAGE/'policy.json').read_text());assert policy['version']=='2026-11-21.2'
    backup=STAGE/'rollback';backup.mkdir(exist_ok=True)
    targets=[(STAGE/name,ROOT/name) for name in NAMES]+[(STAGE/'policy.json',ROOT/'project-memory/policy.json')]
    before={}
    for source,target in targets:
        before[str(target)]=target.exists()
        if target.exists():
            saved=backup/(target.name if target.name!='policy.json' else 'previous-policy.json')
            if saved.exists():raise ValueError('Existing install backup; inspect before repeating')
            shutil.copy2(target,saved)
    service('stop','relax-codex-dispatch.timer')
    installed=[]
    try:
        deadline=time.monotonic()+20
        while subprocess.run(['systemctl','is-active','--quiet','relax-codex-dispatch.service']).returncode==0:
            if time.monotonic()>deadline:raise RuntimeError('Wait for active dispatch before installing')
            time.sleep(2)
        # Seed memory first; consumers are installed only after all contexts validate.
        for source,target in [targets[0],targets[-1]]:
            target.parent.mkdir(exist_ok=True);temp=target.with_suffix('.installing')
            shutil.copy2(source,temp);temp.replace(target);installed.append(target)
        sys.path.insert(0,str(ROOT));import project_memory
        spec=importlib.util.spec_from_file_location('memory_seed_bridge',ROOT/'approval-bridge.py')
        bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        rows=bridge.read_rows(Path('/var/lib/relax-factory'))
        result=project_memory.refresh(rows)
        checks=[]
        for label in ['Quiet Pines Cabin','Little Paris Jazz Cafe','Mountain View Cafe','Exhale to Sleep']:
            for stage in ['planning','image_qc','video_qc','preview_qc']:
                memory=project_memory.context(label,stage=stage,request='снег кот камин звук')
                checks.append(dict(channel=memory['channel'],stage=stage,chars=len(json.dumps(memory,ensure_ascii=False))))
        for job_id in ['20261120-172726-0c72','20261120-193942-cd69','20261120-193143-4575']:
            row=rows[job_id];memory=project_memory.context(row['label'],job_id=job_id,row=row,request='снег кот')
            assert memory['episode']['owner_decision']['status']==row['status']
        for source,target in targets[1:-1]:
            temp=target.with_suffix('.installing');shutil.copy2(source,temp);temp.replace(target);installed.append(target)
        receipt=dict(installed=True,policy_version=policy['version'],memory=result,contexts=checks,
            model_calls=0,owner_approvals_changed=False,render_or_publication_started=False,
            backups=str(backup))
        (ROOT/'project-memory/install-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        print(json.dumps(receipt,ensure_ascii=False))
    except Exception:
        for target in reversed(installed):
            if before[str(target)]:
                saved=backup/(target.name if target.name!='policy.json' else 'previous-policy.json')
                shutil.copy2(saved,target)
            else:target.unlink(missing_ok=True)
        raise
    finally:service('start','relax-codex-dispatch.timer')


if __name__=='__main__':main()
