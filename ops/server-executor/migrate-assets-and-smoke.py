"""Verify portable input archive, extract safely and render a bounded server test."""
import hashlib,json,pathlib,shutil,subprocess,tarfile,time

ROOT=pathlib.Path('/opt/relax-codex')
DATA=pathlib.Path('/var/lib/relax-factory')
EXPECTED='08145ee629eaed8dc04224b4bb147d4fc6b7af6b18411b5242c3272283ca0a13'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def main():
    folder=ROOT/'migration';archive=folder/'relax-portable-assets-20261120.tar.gz'
    manifest=folder/'relax-portable-assets-20261120-manifest.json'
    deadline=time.monotonic()+3600
    while not manifest.exists() or not archive.exists() or archive.stat().st_size!=273546689:
        if time.monotonic()>deadline:raise TimeoutError('Archive transfer incomplete')
        time.sleep(10)
    if digest(archive)!=EXPECTED:raise ValueError('Archive is incomplete or changed')
    library=DATA/'sources/executor-library';library.mkdir(parents=True,exist_ok=True)
    rows=json.loads(manifest.read_text());assets=library/'assets';assets.mkdir(exist_ok=True)
    with tarfile.open(archive,'r:gz') as tar:tar.extractall(assets,filter='data')
    for row in rows:
        p=(assets/row['path']).resolve()
        if assets.resolve() not in p.parents or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:
            raise ValueError('Asset failed verification: '+row['path'])
    tools=library/'tools';tools.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'exhale-portable.py',tools/'exhale-portable.py')
    image=subprocess.run(['docker','inspect','--format','{{.Image}}','relax-factory'],
                         check=True,capture_output=True,text=True).stdout.strip()
    output=library/'tests/exhale';output.mkdir(parents=True,exist_ok=True)
    command=['docker','run','--rm','--name','relax-exhale-smoke','--memory','512m','--cpus','1',
        '--network','none','--volumes-from','relax-factory','--env',
        'PYTHONPATH=/data/sources/executor-library/runtime/python3.12','--entrypoint','python',image,
        '/data/sources/executor-library/tools/exhale-portable.py','--assets','/data/sources/executor-library/assets',
        '--output','/data/sources/executor-library/tests/exhale','--number','1']
    result=subprocess.run(command,check=True,capture_output=True,text=True,timeout=900)
    rendered=json.loads(result.stdout)
    receipt=dict(stage='SERVER_PREVIEW_REBUILT',assets_verified=len(rows),archive_sha256=EXPECTED,
        generated_on_server=True,mac_programs_used=False,memory_limit_mb=512,
        new_paid_generations=0,approval_changed=False,long_final_started=False,render=rendered)
    (folder/'portable-migration-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
