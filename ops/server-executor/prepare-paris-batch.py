"""Deliver seven existing reviewed Paris previews as their complete copies arrive."""
import hashlib,json,subprocess,time
from pathlib import Path

ROOT=Path('/opt/relax-codex')
BATCH=ROOT/'assets/little-paris-dec16-22-20261120'
DATA=Path('/var/lib/relax-factory')


def run(args,timeout=240):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout).stdout


def main():
    rows=json.loads((BATCH/'manifest.json').read_text())
    container_data=run(['docker','exec','relax-factory','python','-c',
                        "import os; print(os.environ.get('APP_DATA','/app/data'))"]).strip()
    run(['docker','cp',str(ROOT/'register-paris-preview.py'),'relax-factory:/tmp/register-paris-preview.py'])
    run(['docker','cp',str(BATCH/'manifest.json'),'relax-factory:/tmp/little-paris-dec16-22-manifest.json'])
    for row in rows:
        number=row['episode'];source=BATCH/row['file'];receipt=BATCH/f'{number}-delivery.json'
        if receipt.exists():
            prior=json.loads(receipt.read_text())
            if prior.get('stage')=='sent':continue
            raise ValueError('Inspect uncertain previous delivery before retry')
        deadline=time.monotonic()+1800
        while not source.exists() or source.stat().st_size!=row['bytes']:
            if time.monotonic()>deadline:raise TimeoutError('Source transfer incomplete')
            time.sleep(5)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Transfer hash mismatch')
        run(['docker','cp',str(source),'relax-factory:/tmp/'+row['file']])
        run(['docker','exec','relax-factory','ffmpeg','-v','error','-nostdin','-threads','2',
             '-i','/tmp/'+row['file'],'-f','null','-'],timeout=180)
        registered=json.loads(run(['docker','exec','relax-factory','python','/tmp/register-paris-preview.py',str(number)]))
        if registered['state']!='registered':raise ValueError(str(registered))
        job_id=registered['job_id'];folder=DATA/job_id
        prepared=json.loads((folder/'paris-production-manifest.json').read_text())
        tracks=[]
        for name in prepared['server_tracks']:
            p=folder/'tracks'/name
            sec=float(run(['docker','exec','relax-factory','ffprobe','-v','error','-show_entries',
                           'format=duration','-of','default=nw=1:nk=1',container_data+'/'+job_id+'/tracks/'+name]))
            if sec<=30:raise ValueError('Music must contain full tracks')
            tracks.append(dict(name=name,seconds=sec,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        cover=BATCH/f'{number}-cover.jpg'
        run(['docker','exec','relax-factory','ffmpeg','-v','error','-y','-ss','2','-i',
             '/tmp/'+row['file'],'-frames:v','1','-threads','1',f'/tmp/paris-{number}-cover.jpg'])
        run(['docker','cp',f'relax-factory:/tmp/paris-{number}-cover.jpg',str(cover)])
        scene=row['label'].split(' — ')[1].split(' ',1)[1]
        description=(f'A quiet snowy cafe scene inspired by {scene}, with warm lights and gentle winter jazz.\n\n'
                     'Three hours for reading, working or relaxing. No talking.\n\n'
                     'AI-generated scenery, edited with a separate snowfall layer.\n\nMusic:\n')
        elapsed=0
        for track in tracks:
            t=int(elapsed);description+=f'{t//3600:02d}:{t//60%60:02d}:{t%60:02d} '+track['name'].split(' — ',1)[-1].removesuffix('.mp3')+'\n'
            elapsed+=track['seconds']-3
        manifest=dict(job_id=job_id,channel='Little Paris Jazz Cafe',profile='Little_Paris_Jazz_Cafe',
            publish_at=row['date'],hours=3,preview_sha256=row['sha256'],recipe_verified=True,
            recipe_basis='Exact reviewed 30-second whole-frame loop, existing separate snow layer; complete full-track album',
            full_tracks=tracks,cover_path=str(cover),
            title=f'Snowy {scene} Cafe | Cozy Winter Jazz | 3 Hours',description=description,
            tags='winter jazz, cozy cafe, relaxing jazz, snowy cafe, cafe ambience, little paris jazz cafe')
        manifests=ROOT/'publication-manifests';manifests.mkdir(exist_ok=True)
        target=manifests/(job_id+'.json')
        with target.open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
        receipt.write_text(json.dumps(dict(stage='telegram_submission_uncertain',job_id=job_id,date=row['date'])))
        run(['docker','exec','relax-factory','python','-c',
             "import runpy,sys; n=runpy.run_path('/tmp/register-paris-preview.py'); n['call']('/jobs/'+sys.argv[1]+'/telegram','POST',b'')",job_id])
        end=time.monotonic()+180
        while time.monotonic()<end:
            d=json.loads((folder/'job.json').read_text());status=(d.get('telegram') or {}).get('status')
            if status=='отправлено':break
            if status=='ошибка':raise ValueError('Telegram delivery failed; inspect before retry')
            time.sleep(3)
        else:raise TimeoutError('Uncertain Telegram delivery; no duplicate retry')
        receipt.write_text(json.dumps(dict(stage='sent',job_id=job_id,date=row['date']),ensure_ascii=False,indent=2))
        print('SENT',number,job_id,row['date'],flush=True)


if __name__=='__main__':main()
