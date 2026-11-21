import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cabin_backlog_registry as backlog
"""Finish one staged Cabin test: prescreen, register recipe, send owner preview.
No owner approval or long render. Idle waits do not call a model.
"""
import argparse,fcntl,hashlib,json,re,subprocess,time
from pathlib import Path
from motion_policy import VERSION, moving_regions

ROOT=Path('/opt/relax-codex')
DATA=Path('/var/lib/relax-factory')


def run(args,timeout=900):
    return subprocess.run(args,check=True,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,timeout=timeout)


def read(p):return json.loads(p.read_text()) if p.exists() else None


def notify_hold(folder,reason):
    marker=folder/'attention-notification.json'
    if marker.exists():return
    marker.write_text(json.dumps({'state':'sending','reason':reason}))
    day=folder.name[5:7]
    text=(f'Проба Quiet Pines Cabin на {int(day)} декабря пока не готова. '
          'Автоматическая проверка или сервис генерации требуют внимания. '
          'Материалы и история сохранены; брак в публикацию не отправлялся.')
    try:
        run(['docker','exec','relax-factory','python','-c',
             'import sys; from render import telegram; telegram.send_text(sys.argv[1])',text],timeout=90)
        marker.write_text(json.dumps({'state':'sent','reason':reason}))
    except Exception:
        marker.write_text(json.dumps({'state':'unconfirmed_no_retry','reason':reason}))


def main(group):
    if not backlog.group(group):raise ValueError('Unsupported prepared series')
    folder=ROOT/'production-runs'/group
    with (folder/'finisher.lock').open('w') as lock:
        # A recovery follower may arrive while the prior one is notifying an
        # outage. Serialize the handover; the durable receipt prevents resends.
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            with (ROOT/'cabin-backlog/media-check.lock').open('a') as media_lock:
                fcntl.flock(media_lock,fcntl.LOCK_EX)
                finish(group,folder)
        except Exception as error:
            receipt=folder/'delivery.json'
            value=read(receipt) or {}
            value.update(stage='finisher_failed_no_retry',error=type(error).__name__,updated=time.time())
            receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2))
            notify_hold(folder,'finisher_failed_no_retry')
            raise


def finish(group,folder):
    receipt=folder/'delivery.json'
    old=read(receipt)
    if old and old.get('stage')=='sent_for_owner_approval':return
    config=read(ROOT/'production-configs'/(group+'.json'))
    started=time.monotonic()
    deadline=started+10800
    rejected=set((old or {}).get('rejected_requests',[]))
    def save(stage,**details):
        p=folder/'delivery.tmp';p.write_text(json.dumps(dict(stage=stage,updated=time.time(),motion_policy_version=VERSION,
            rejected_requests=sorted(rejected),**details),ensure_ascii=False,indent=2));p.replace(receipt)
    save('waiting_for_checked_preview',previous_stage=(old or {}).get('stage'))
    while time.monotonic()<deadline:
        state=read(folder/'state.json') or {}
        if state.get('stage') in ('prepared_source_pool_exhausted','provider_unavailable_no_image_purchase',
            'model_unavailable_no_retry','submission_slots_exhausted_no_image_purchase',
            'technical_attention_required','preparation_failed_no_submission','recover_existing_video','recover_existing_image'):
            # A producer launched asynchronously alongside us may not have
            # replaced its prior terminal state yet. Give it startup time.
            if time.monotonic()-started<30:
                time.sleep(2);continue
            save('held_for_inspection',production=state)
            notify_hold(folder,state['stage']);return
        if state.get('stage')!='preview_ready_for_final_checks':time.sleep(10);continue
        rid=state['request_id']
        if rid in rejected:
            previous=read(ROOT/'assets'/rid/'pipeline.json') or {}
            save('deferred_after_preview_rejection',request_id=rid,
                 defects=previous.get('defects',['This exact version already failed final review']))
            return
        assets=ROOT/'assets'/rid;prefix='/tmp/'+rid
        backlog.stage_geometry(rid,backlog.geometry(rid))
        save('final_prescreen',request_id=rid)
        for name in ['head-motion.py','media-screen.py','check-publication-loop.py','deliver-preview.py']:
            run(['docker','cp',str(ROOT/('cabin-backlog/'+name if name in ['production-retry.py', 'pipeline-one.py', 'finish-production.py', 'try-long-segment.py', 'final-preview-review.py', 'deliver-preview.py', 'head-motion.py', 'source-review.py'] else name)),'relax-factory:/tmp/'+name])
        # Restore persistent media after a factory restart; never regenerate it.
        run(['docker','exec','relax-factory','mkdir','-p',prefix])
        run(['docker','cp',str(assets/'preview.mp4'),'relax-factory:'+prefix+'/preview.mp4'])
        audio=ROOT/'assets/cabin-approved-fireplace-9.wav'
        run(['docker','cp',str(audio),'relax-factory:'+prefix+'/audio.wav'])
        media=json.loads(run(['docker','exec','relax-factory','python','/tmp/media-screen.py',rid]).stdout)
        (assets/'media-screen.json').write_text(json.dumps(media,indent=2))
        motion=json.loads(run(['docker','exec','relax-factory','python','/tmp/head-motion.py',rid,
                              '--filename','preview.mp4'],timeout=180).stdout)
        (assets/'preview-head-motion.json').write_text(json.dumps(motion,indent=2))
        moving=moving_regions(motion)
        defects=[]
        if not media['technical_screen_passed']:
            defects.append('Technical frame/audio screen failed')
        if moving:(assets/'numeric-motion-flags.json').write_text(json.dumps({'regions':moving,'metrics':motion,'requires_visual_review':True},indent=2))
        if not defects:
            visual=json.loads(run(['/usr/bin/python3',str(ROOT/'cabin-backlog'/'final-preview-review.py'),rid],timeout=300).stdout)
            if visual.get('outdoor_snow')=='UNCERTAIN':
                pipeline=read(assets/'pipeline.json');pipeline.update(stage='held_for_snow_evidence',updated=time.time(),defects=visual['defects'])
                (assets/'pipeline.json').write_text(json.dumps(pipeline,ensure_ascii=False,indent=2))
                save('quality_evidence_requires_review',request_id=rid,
                     reason='Snow evidence uncertain; do not spend another generation on uncertainty')
                return
            if visual['verdict']!='READY_FOR_OWNER_PREVIEW':defects+=visual['defects'] or ['Visual prescreen rejected']
        if defects:
            pipeline=read(assets/'pipeline.json');pipeline.update(stage='rejected_preview',defects=defects,updated=time.time(),motion_policy_version=VERSION)
            (assets/'pipeline.json').write_text(json.dumps(pipeline,ensure_ascii=False,indent=2))
            rejected.add(rid);save('retrying_after_preview_rejection',request_id=rid,defects=defects)
            save('deferred_after_preview_rejection',request_id=rid,defects=defects)
            return
        built=read(assets/'recipe-and-checks.json') or {}
        if built.get('publication_loop_mode')=='repeat':
            for src,dst in [(assets/'recipe-and-checks.json',prefix+'/recipe-and-checks.json'),
                            (assets/'loop-master.mp4',prefix+'/loop-master.mp4'),
                            (ROOT/'cabin_loop_recipe.py','/tmp/cabin_loop_recipe.py')]:
                run(['docker','cp',str(src),'relax-factory:'+dst])
        recipe=json.loads(run(['docker','exec','relax-factory','python','/tmp/check-publication-loop.py',rid]).stdout)
        (assets/'publication-loop-check.json').write_text(json.dumps(recipe,indent=2))
        run(['docker','exec','relax-factory','ffmpeg','-nostdin','-v','error','-y','-threads','1',
             '-i',prefix+'/preview.mp4','-frames:v','1','-threads','1',prefix+'/cover.jpg'])
        run(['docker','cp','relax-factory:'+prefix+'/cover.jpg',str(assets/'cover.jpg')])
        ready=dict(ready_for_owner_review=True,review_type='automated_test_prescreen',
            motion_policy_version=VERSION,numeric_motion_flags=moving,numeric_motion_is_approval=False,
            full_frame_only=True,local_masks=False,decoded_frames=media['frames'],
            audio_correlation=media['audio_correlation'],approved_audio_source=str(audio),
            real_time_playback_performed=False,listening_performed=False,
            limitations='Numerical full-sequence checks and sampled visual analysis; owner approval is still required.')
        (assets/'owner-review-ready.json').write_text(json.dumps(ready,indent=2))
        run(['docker','cp',str(assets/'owner-review-ready.json'),'relax-factory:'+prefix+'/owner-review-ready.json'])
        day=group[5:7];scene=config['scene_title']
        label=f'Quiet Pines Cabin — {int(day)} декабря — {scene} — серверная проба — 30 секунд'
        args=['docker','exec','relax-factory','python','/tmp/deliver-preview.py','--request-id',rid,'--label',label]
        registration=json.loads(run(args+['--register-only']).stdout)
        registration=registration.get('held_existing_delivery',registration)
        if registration['stage'] not in ('registered','telegram_requested'):
            save('delivery_requires_inspection',record=registration);return
        job_id=registration['job_id']
        manifest=dict(job_id=job_id,channel='Quiet Pines Cabin',profile='Quiet_Pines',
            publish_at=config['publish_at'],hours=3,recipe_verified=recipe['validated_with_factory_engine'],
            loop_crossfade_seconds=.75,loop_test_seconds=recipe['loop_seconds'],
            preview_sha256=hashlib.sha256((assets/'preview.mp4').read_bytes()).hexdigest(),
            audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),cover_path=str(assets/'cover.jpg'),
            title=config['english_title']+' & Crackling Fireplace | Sleeping Cat | 3 Hours',
            description='Relax in a warm wooden cabin with a sleeping cat, a crackling fireplace and snowfall outside the closed windows.\n\nThree hours of fireplace ambience for reading, relaxing and winding down. No music or wind in the audio.\n\nThis scene was created with AI and edited for Quiet Pines Cabin.',
            tags='cozy cabin, crackling fireplace, fireplace sounds, sleeping cat, snowy forest, winter ambience, relaxing ambience, quiet pines cabin')
        if recipe.get('publication_loop_mode')=='repeat':
            manifest.update(publication_loop_mode='repeat',loop_crossfade_seconds=0,
                loop_builder_version=recipe['loop_builder_version'],loop_master_path=str(assets/'loop-master.mp4'),
                loop_master_sha256=recipe['loop_master_sha256'])
        from christmas_titles import title_for
        manifest['title']=title_for(manifest['channel'],manifest['title'])
        from public_metadata import description_for,tags_for
        manifest['description']=description_for(manifest['channel'],manifest['title'],manifest.get('description',''))
        manifest['tags']=', '.join(tags_for(manifest['channel'],manifest['title']))
        manifest['public_metadata_policy']='2026-11-21-seasonal-keywords-v1'
        manifests=ROOT/'publication-manifests';manifests.mkdir(exist_ok=True)
        target=manifests/(job_id+'.json')
        if target.exists() and read(target)!=manifest:raise ValueError('Existing publication manifest differs')
        target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        run(['docker','cp',str(target),'relax-factory:/tmp/codex-manifest-'+job_id+'.json'])
        save('sending_registered_preview',job_id=job_id,request_id=rid)
        if registration['stage']=='registered':run(args+['--send-registered'])
        for _ in range(24):
            job=read(DATA/job_id/'job.json') or {}
            if (job.get('telegram') or {}).get('status')=='отправлено':
                save('sent_for_owner_approval',job_id=job_id,request_id=rid,publish_at=config['publish_at'],
                     long_final_started=False);return
            time.sleep(5)
        save('telegram_delivery_unconfirmed_no_retry',job_id=job_id,request_id=rid);return
    save('wait_expired_no_duplicate_delivery')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('group');main(p.parse_args().group)
