"""Restore publication recipes for nine exact approved legacy Paris previews.

No approval changes, generation, final renders or automatic replacement of inputs.
Promotion uses the existing guarded publisher as a separate step.
"""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

ROOT=Path('/opt/relax-codex');DATA=Path('/var/lib/relax-factory')
POOL=DATA/'sources/executor-library/assets/music/little-paris'
BATCH=ROOT/'assets/little-paris-dec06-14-20261121'

def run(args,timeout=180):
    return subprocess.run(args,capture_output=True,text=True,check=True,timeout=timeout).stdout

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def container_path(path):return '/data/'+str(path.relative_to(DATA))

def main(tallinn_only=False):
    batch=ROOT/'assets/little-paris-tallinn-20261121' if tallinn_only else BATCH
    report='tallinn-audio-check.jsonl' if tallinn_only else 'paris-backlog-audio-check.jsonl'
    rows=[json.loads(s) for s in (ROOT/report).read_text().splitlines() if s]
    count=1 if tallinn_only else 9
    if len(rows)!=count or len({r['job_id'] for r in rows})!=count:raise ValueError('Incomplete identity check')
    if tallinn_only and rows[0]['job_id']!='20261119-181826-3a91':raise ValueError('Unexpected waiting source')
    catalog={r['name']:r for r in json.loads((POOL/'catalog.json').read_text())}
    plans=json.loads((DATA/'approved-production-queue.json').read_text())
    batch.mkdir(exist_ok=True)
    # Validate the complete album once. Original approved excerpts use tracks 11..20.
    names=sorted(n for n in catalog if 11<=int(n.split(' ',1)[0])<=20)
    if len(names)!=10:raise ValueError('Full album incomplete')
    tracks={}
    for name in names:
        path=POOL/name
        if sha(path)!=catalog[name]['sha256']:raise ValueError('Library hash mismatch')
        seconds=float(run(['docker','exec','relax-factory','ffprobe','-v','error','-show_entries',
                           'format=duration','-of','default=nw=1:nk=1',container_path(path)]))
        if not 60<seconds<900:raise ValueError('Invalid complete track length')
        tracks[name]={'seconds':seconds,'sha256':catalog[name]['sha256']}
    for row in sorted(rows,key=lambda r:r['date']):
        jid=row['job_id'];folder=DATA/jid;meta=json.loads((folder/'job.json').read_text())
        allowed=('одобрено','ждёт') if tallinn_only else ('одобрено',)
        planned=plans.get(jid,{}).get('publish_at','2026-12-15T22:00' if tallinn_only else '')
        if (meta.get('approval',{}).get('status') not in allowed or meta.get('status')!='готово'
                or meta['label']!=row['label'] or planned!=row['date']):
            raise ValueError('Current decision or reserved date changed')
        if not '2026-12-06'<=row['date'][:10]<=('2026-12-15' if tallinn_only else '2026-12-14'):raise ValueError('Unexpected date')
        first=row['matches'][0][1]
        if (row['matches'][0][0]<.985 or row['matches'][0][0]-row['matches'][1][0]<.2
                or first not in tracks):raise ValueError('Ambiguous original music')
        source=folder/Path(meta['output']).name;digest=sha(source)
        if any((folder/'mask').iterdir()):raise ValueError('Unexpected masks')
        visual=folder/'visual/approved-master.mp4'
        if any(p!=visual for p in (folder/'visual').iterdir()):raise ValueError('Unexpected visual sources')
        if visual.exists():
            if sha(visual)!=digest:raise ValueError('Existing visual changed')
        else:os.link(source,visual)
        order=[first]+[n for n in names if n!=first];full=[]
        expected={f'{i:03d} — {n}' for i,n in enumerate(order,1)}
        if any(p.name not in expected for p in (folder/'tracks').iterdir()):raise ValueError('Unexpected tracks')
        for i,n in enumerate(order,1):
            dest=folder/'tracks'/f'{i:03d} — {n}'
            if not dest.exists():os.link(POOL/n,dest)
            if sha(dest)!=tracks[n]['sha256']:raise ValueError('Existing track changed')
            full.append(dict(name=dest.name,**tracks[n]))
        probe=json.loads(run(['docker','exec','relax-factory','ffprobe','-v','error','-show_streams',
                             '-show_format','-of','json',container_path(source)]))
        video=next(s for s in probe['streams'] if s['codec_type']=='video')
        if not (video['width']==1920 and video['height']==1080 and video['r_frame_rate']=='24/1'
                and abs(float(probe['format']['duration'])-30)<.15):raise ValueError('Unexpected preview format')
        run(['docker','exec','relax-factory','ffmpeg','-v','error','-nostdin','-threads','2',
             '-i',container_path(source),'-f','null','-'])
        cover=batch/(jid+'-cover.jpg')
        run(['docker','exec','relax-factory','ffmpeg','-v','error','-nostdin','-y','-ss','2',
             '-i',container_path(source),'-frames:v','1','-threads','1','/tmp/'+cover.name])
        run(['docker','cp','relax-factory:/tmp/'+cover.name,str(cover)])
        scene=meta['label'].split(' — ')[1].split(' ',1)[1]
        description=(f'A quiet snowy cafe scene inspired by {scene}, with warm lights and gentle winter jazz.\n\n'
            'Three hours for reading, working or relaxing. No talking.\n\n'
            'AI-generated scenery, edited with a separate snowfall layer.\n\nMusic:\n')
        elapsed=0
        for track in full:
            t=int(elapsed);description+=f'{t//3600:02d}:{t//60%60:02d}:{t%60:02d} '+track['name'].split(' — ',1)[-1].removesuffix('.mp3')+'\n'
            elapsed+=track['seconds']-3
        manifest=dict(job_id=jid,channel='Little Paris Jazz Cafe',profile='Little_Paris_Jazz_Cafe',
            publish_at=row['date'],hours=3,preview_sha256=digest,recipe_verified=True,
            recipe_basis='Exact owner-approved whole-frame 30s snow loop; complete album matched to original preview audio',
            audio_identity=row['matches'],full_tracks=full,cover_path=str(cover),
            title=f'Snowy {scene} Cafe | Cozy Winter Jazz | 3 Hours',description=description,
            tags='winter jazz, cozy cafe, relaxing jazz, snowy cafe, cafe ambience, little paris jazz cafe')
        target=ROOT/'publication-manifests'/(jid+'.json')
        if target.exists():
            if json.loads(target.read_text())!=manifest:raise ValueError('Existing manifest differs')
        else:
            with target.open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
        (batch/(jid+'-validated.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        print(json.dumps({'prepared':jid,'date':row['date'],'first_track':first},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tallinn-only',action='store_true')
    main(p.parse_args().tallinn_only)
