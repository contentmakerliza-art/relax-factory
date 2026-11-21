"""Factory-side publication of an exact approved version with a prepared manifest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy


def main(job_id):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}',job_id):raise ValueError('Invalid source')
    manifest=json.loads((Path('/tmp')/('codex-manifest-'+job_id+'.json')).read_text())
    from christmas_titles import title_for
    manifest['title']=title_for(manifest['channel'],manifest['title'])
    from public_metadata import description_for,tags_for
    manifest['description']=description_for(manifest['channel'],manifest['title'],manifest.get('description',''))
    manifest['tags']=', '.join(tags_for(manifest['channel'],manifest['title']))
    profiles={'Quiet_Pines':'Quiet Pines Cabin','Little_Paris_Jazz_Cafe':'Little Paris Jazz Cafe'}
    if (manifest['job_id']!=job_id or profiles.get(manifest['profile'])!=manifest['channel']
            or not manifest['recipe_verified']):
        raise ValueError('Unsupported or unverified publication manifest')
    call=runpy.run_path('/tmp/prepare-publication.py')['call']
    queue=call('/queue');existing=[r for r in queue if r.get('source')==job_id]
    if existing:
        if len(existing)!=1 or existing[0]['publish_at']!=manifest['publish_at'] or existing[0]['user']!=manifest['profile']:
            raise ValueError('Existing publication differs; inspect without changing it')
        print(json.dumps({'publication':existing[0],'already_queued':True},ensure_ascii=False));return
    if any(r.get('user')==manifest['profile'] and r.get('publish_at','')[:10]==manifest['publish_at'][:10] for r in queue):
        raise ValueError('Requested channel/date already occupied')
    data=Path(os.environ.get('APP_DATA','/app/data'));folder=data/job_id
    meta=json.loads((folder/'job.json').read_text())
    if (meta.get('approval') or {}).get('status')!='одобрено' or meta.get('status')!='готово':
        raise ValueError('Exact source is not approved and ready')
    approved=folder/Path(meta['output']).name
    if hashlib.sha256(approved.read_bytes()).hexdigest()!=manifest['preview_sha256']:
        raise ValueError('Approved preview changed; do not publish')
    if (folder/'mask').exists() and any((folder/'mask').iterdir()):raise ValueError('Unexpected local masks')
    if manifest['profile']=='Quiet_Pines':
        audio=call('/jobs/'+job_id+'/background-audio')
        if audio.get('sha256')!=manifest['audio_sha256']:
            audio=call('/jobs/'+job_id+'/background-audio','POST',{},
                       ('file',Path('/tmp/cabin-full-fireplace-9.wav'),'audio/wav'))
        if audio['sha256']!=manifest['audio_sha256'] or audio['seconds']<100:
            raise ValueError('Complete approved audio is missing')
    else:
        if len(manifest.get('full_tracks',[]))<6:raise ValueError('Full musical album required')
        for track in manifest['full_tracks']:
            path=folder/'tracks'/track['name']
            if (path.parent!=folder/'tracks' or track['seconds']<=30
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=track['sha256']):
                raise ValueError('Full track changed or is missing')
        visual=folder/'visual'/'approved-master.mp4'
        if hashlib.sha256(visual.read_bytes()).hexdigest()!=manifest['preview_sha256']:
            raise ValueError('Approved whole-frame visual is missing')
    # Queue render reads its settings from this persisted metadata. Preview bytes stay intact.
    meta=json.loads((folder/'job.json').read_text())
    if (meta.get('approval') or {}).get('status')!='одобрено':raise ValueError('Approval changed')
    history=folder/'codex-recipe-history';history.mkdir(exist_ok=True)
    backup=history/'job-before-automatic-publication.json'
    if not backup.exists():backup.write_text(json.dumps(meta,ensure_ascii=False))
    meta['settings'].update(loop_mode='crossfade' if manifest['profile']=='Quiet_Pines' else 'chain',
                            loop_crossfade=.75 if manifest['profile']=='Quiet_Pines' else 0,
                            width=1920,height=1080,fps=24,find_loop_point=False,
                            stabilize=False,smooth=False,speed=1,stab_mask='')
    if manifest['profile']=='Little_Paris_Jazz_Cafe':
        meta['settings'].update(loudness=-19,track_crossfade=3,shuffle_tracks=False,logo='')
        meta['tracks']=len(manifest['full_tracks'])
    temporary=folder/'codex-publication-settings.tmp';temporary.write_text(json.dumps(meta,ensure_ascii=False));temporary.replace(folder/'job.json')
    (folder/'codex-publication-recipe.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    values={'source':job_id,'title':manifest['title'],'description':manifest['description'],
            'tags':manifest['tags'],'publish_at':manifest['publish_at'],'user':manifest['profile'],
            'hours':'3','bitrate':'4','synthetic':'true','draft':'false','render_now':'false'}
    result=call('/queue','POST',values,('cover_file',Path('/tmp')/('codex-cover-'+job_id+'.jpg'),'image/jpeg'))
    print(json.dumps({'publication':result,'already_queued':False},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job_id');main(p.parse_args().job_id)
