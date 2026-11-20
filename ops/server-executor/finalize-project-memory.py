"""Apply validated memory-only updates and produce a consistent private backup."""
import fcntl, importlib.util, json, shutil, sys, time
from pathlib import Path

ROOT=Path('/opt/relax-codex')
STAGE=ROOT/'staging/memory-20261121'

def main():
    pending=[(STAGE/'project_memory.latest.py',ROOT/'project_memory.py'),
             (STAGE/'policy.latest.json',ROOT/'project-memory/policy.json')]
    compile(pending[0][0].read_text(),str(pending[0][0]),'exec')
    assert json.loads(pending[1][0].read_text())['schema']==1
    for source,target in pending:
        if source.read_bytes()==target.read_bytes():continue
        backup=STAGE/'rollback'/(target.name+'.before-final')
        if not backup.exists():shutil.copy2(target,backup)
        temp=target.with_name(target.name+'.finalizing')
        shutil.copy2(source,temp);temp.replace(target)
    sys.path.insert(0,str(ROOT));import project_memory
    spec=importlib.util.spec_from_file_location('memory_backup_bridge',ROOT/'approval-bridge.py')
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    result=project_memory.refresh(bridge.read_rows(Path('/var/lib/relax-factory')))
    memory=ROOT/'project-memory'
    with (memory/'refresh.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        snapshot={'schema':1,'created_at_unix':time.time(),
                  'provenance':'Passports, bot decisions and infrastructure. Claude chats were absent from export.',
                  'files':{str(p.relative_to(memory)):json.loads(p.read_text())
                    for p in sorted(memory.rglob('*.json'))
                    if not p.name.startswith('backup-')}}
        output=memory/'backup-20261121.json'
        project_memory.write(output,snapshot)
    print(json.dumps({'memory':result,'snapshot':str(output),'bytes':output.stat().st_size}))

if __name__=='__main__':main()
