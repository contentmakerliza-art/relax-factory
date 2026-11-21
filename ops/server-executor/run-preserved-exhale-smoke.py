"""Stage inputs and run a memory-bounded offline full-intro smoke test."""
import json,shutil,subprocess,time
from pathlib import Path

ROOT=Path('/opt/relax-codex');STAGE=ROOT/'staging';LIB=Path('/var/lib/relax-factory/sources/executor-library')

def main():
    subprocess.run(['python3',str(STAGE/'prepare-exhale-publications.py')],check=True)
    pack=LIB/'tools/exhale-render-staging';pack.mkdir(exist_ok=True)
    shutil.copytree('/opt/relax-factory/render',pack/'render',dirs_exist_ok=True)
    for name in ['engine.py','preserved_exhale.py']:shutil.copy2(STAGE/name,pack/'render'/name)
    shutil.copy2(STAGE/'smoke-preserved-exhale.py',pack/'smoke-preserved-exhale.py')
    output=LIB/'tests/preserved-exhale';output.mkdir(exist_ok=True)
    image=subprocess.run(['docker','inspect','--format','{{.Image}}','relax-factory'],check=True,capture_output=True,text=True).stdout.strip()
    start=time.time()
    with (output/'run.log').open('w') as log:
        result=subprocess.run(['docker','run','--rm','--name','relax-exhale-preserved-smoke','--memory','512m',
            '--cpus','1','--network','none','--volumes-from','relax-factory','--env','OPENBLAS_NUM_THREADS=1',
            '--env','PYTHONPATH=/data/sources/executor-library/runtime/python3.12','--entrypoint','python',image,
            '/data/sources/executor-library/tools/exhale-render-staging/smoke-preserved-exhale.py','--number','1'],
            stdout=log,stderr=subprocess.STDOUT,timeout=2400)
    record=dict(exit_code=result.returncode,elapsed_seconds=time.time()-start,memory_limit_mb=512,
                cpu_limit=1,network=False,approval_changed=False,final_ten_hours_started=False)
    (output/'run-receipt.json').write_text(json.dumps(record,indent=2))
    if result.returncode:raise RuntimeError('Inspect full-intro smoke log')
    print(json.dumps(record),flush=True)

if __name__=='__main__':main()
