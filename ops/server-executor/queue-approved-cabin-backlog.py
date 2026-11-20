"""Queue four explicit owner-approved legacy Cabin versions without remaking them.

Run in factory container; preserve exact chain recipe, restore complete audio,
and use the dates explicitly named on these four previews. Durable queue ledger.
"""
import hashlib,json,os,runpy,subprocess,time
from pathlib import Path

DATA=Path(os.environ.get('APP_DATA','/data'))
ROWS=[('20261119-203840-ac20','04','Artist Cabin Studio'),
      ('20261119-204114-a9a4','13','Birch Forest Cabin'),
      ('20261119-204154-d82e','14','Cozy Cabin Sitting Room'),
      ('20261119-205140-f946','16','Winter Craft Cabin')]

def main():
    call=runpy.run_path('/tmp/prepare-publication.py')['call']
    for jid,day,name in ROWS:
        folder=DATA/jid;meta=json.loads((folder/'job.json').read_text())
        when='2026-12-'+day+'T22:00';ledger=folder/'backlog-publication-receipt.json'
        existing=[r for r in call('/queue') if r.get('source')==jid]
        if existing:
            if len(existing)!=1 or existing[0]['publish_at']!=when:raise ValueError('Unexpected existing queue date')
            print(json.dumps({'already_queued':jid,'date':when}),flush=True);continue
        if ledger.exists():raise ValueError('Inspect uncertain earlier publication before retry')
        if meta.get('approval',{}).get('status')!='одобрено' or meta['status']!='готово':raise ValueError('Approval changed')
        if (' — '+day+' декабря — ') not in meta['label']:raise ValueError('Explicit preview date differs')
        settings=meta['settings']
        if not (settings['loop_mode']=='chain' and settings['loop_crossfade']==0
                and not settings['stabilize'] and settings['speed']==1):raise ValueError('Existing exact recipe differs')
        output=folder/meta['output'];digest=hashlib.sha256(output.read_bytes()).hexdigest()
        if hashlib.sha256((folder/'visual/approved-master.mp4').read_bytes()).hexdigest()!=digest:raise ValueError('Master differs')
        if any((folder/'mask').iterdir()):raise ValueError('Unexpected local mask')
        title=name+' & Crackling Fireplace | Sleeping Cat | 3 Hours'
        description=('Relax in a warm wooden cabin with a sleeping cat, a crackling fireplace and snowfall outside.\n\n'
            'Three hours for reading, relaxing and winding down. No music or wind in the audio.\n\n'
            'This scene was created with AI and edited for Quiet Pines Cabin.')
        tags='cozy cabin, crackling fireplace, fireplace sounds, sleeping cat, winter ambience, quiet pines cabin'
        # Validate exact expected reference and a previously measured excerpt identity.
        reference=call('/jobs/20261120-172726-0c72/background-audio')
        expected='5da945ef4e6ba128fe3c2241afd8725d2b366e8a49b4831a7776356310235b5f'
        if reference.get('sha256')!=expected or reference.get('seconds',0)<100:raise ValueError('Complete approved audio changed')
        current=call('/jobs/'+jid+'/background-audio')
        if current.get('sha256')!=expected:
            current=call('/jobs/'+jid+'/background-audio','POST',{'from_job':'20261120-172726-0c72'})
        if current.get('sha256')!=expected:raise ValueError('Audio attachment failed')
        call('/production/'+jid+'/plan','POST',dict(channel='Quiet Pines Cabin',publish_at=when,
             title=title,description=description,tags=tags,profile='Quiet_Pines',hours='3'))
        latest=json.loads((folder/'job.json').read_text())
        if (latest['approval']['status']!='одобрено' or hashlib.sha256(output.read_bytes()).hexdigest()!=digest
                or latest['settings']['loop_crossfade']!=0):raise ValueError('Source changed during preparation')
        cover=Path('/tmp')/(jid+'-backlog-cover.jpg')
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss','2','-i',str(output),
                        '-frames:v','1','-threads','1',str(cover)],check=True,capture_output=True,timeout=90)
        record=dict(state='queue_submission_uncertain',job_id=jid,publish_at=when,
            preview_sha256=digest,full_audio_sha256=expected,created=time.time(),
            recipe='Preserve owner-approved chain loop, no new masks, exact preview unchanged')
        ledger.write_text(json.dumps(record,indent=2))
        result=call('/queue','POST',dict(source=jid,title=title,description=description,tags=tags,
            publish_at=when,user='Quiet_Pines',hours='3',bitrate='4',synthetic='true',draft='false',render_now='false'),
            ('cover_file',cover,'image/jpeg'))
        if result.get('status')!='ждёт' or result.get('publish_at')!=when:raise ValueError('Queue submission requires inspection')
        record.update(state='queued',publication=result);ledger.write_text(json.dumps(record,ensure_ascii=False,indent=2))
        print(json.dumps({'queued':jid,'date':when,'publication_id':result['id']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
