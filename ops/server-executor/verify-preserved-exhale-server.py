"""Run independent opening QA and a first audio-cycle handoff test offline."""
import json,shutil,subprocess,time
from pathlib import Path

ROOT=Path('/opt/relax-codex');LIB=Path('/var/lib/relax-factory/sources/executor-library')

def main():
    pack=LIB/'tools/exhale-render-staging';out=LIB/'tests/preserved-exhale'
    shutil.copy2(ROOT/'staging/preserved_exhale.py',pack/'render/preserved_exhale.py')
    for n in ['check-preserved-exhale.py','smoke-preserved-exhale.py']:shutil.copy2(ROOT/'staging'/n,pack/n)
    image=subprocess.run(['docker','inspect','--format','{{.Image}}','relax-factory'],capture_output=True,text=True,check=True).stdout.strip()
    tasks=[('quality','check-preserved-exhale.py',[]),('handoff','smoke-preserved-exhale.py',['--number','1','--cycle-handoff'])]
    children=[];start=time.time()
    for name,script,extra in tasks:
        log=(out/(name+'.log')).open('w')
        cmd=['docker','run','--rm','--name','relax-exhale-check-'+name,'--memory','512m','--cpus','.5',
            '--network','none','--volumes-from','relax-factory','--env','OPENBLAS_NUM_THREADS=1',
            '--env','PYTHONPATH=/data/sources/executor-library/runtime/python3.12','--entrypoint','python',
            image,'/data/sources/executor-library/tools/exhale-render-staging/'+script,*extra]
        children.append((name,subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT),log))
    results={}
    try:
        for name,child,log in children:results[name]=child.wait(timeout=1800);log.close()
    finally:
        for name,child,log in children:
            if child.poll() is None:child.terminate();child.wait()
            log.close()
    (out/'verification-processes.json').write_text(json.dumps(dict(exit_codes=results,elapsed_seconds=time.time()-start),indent=2))
    print(json.dumps(results),flush=True)
    if any(results.values()):raise RuntimeError('Inspect verification logs')

if __name__=='__main__':main()
