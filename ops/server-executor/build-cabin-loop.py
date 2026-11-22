"""Host wrapper: normalize native motion, close one cycle, repeat that exact cycle."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from cabin_loop_recipe import VERSION
ROOT=Path('/opt/relax-codex')

CODE=r'''
import sys,os,json,subprocess,hashlib
from pathlib import Path
os.environ['OMP_NUM_THREADS']='2';sys.path.insert(0,'/app');sys.path.insert(0,'/tmp')
from render import engine,zoomfix
from cabin_loop_recipe import VERSION,FPS,CROSSFADE,expected_loop_frames,safe_camera_fit
rid=sys.argv[1];base=Path('/tmp')/rid;source=base/'source.mp4'
original=engine._run
def limited(cmd):
 if cmd[0]=='ffmpeg':cmd=cmd[:1]+['-nostdin','-threads','1','-filter_complex_threads','1']+cmd[1:-1]+['-threads','2']+cmd[-1:]
 return original(cmd)
engine._run=limited
measure=zoomfix._measure(source,'')
if not safe_camera_fit(measure):raise ValueError('Camera drift exceeds bounded repair; inspect source')
# Reuse the measured zoom expression instead of repeating image analysis.
if measure:
 idx,found=measure;top=max(v[0] for v in found)
 zoom=zoomfix._perspective(zoomfix._ramp(idx,[top/v[0] for v in found]),
     zoomfix._ramp(idx,[v[2]/320 for v in found]),zoomfix._ramp(idx,[v[1]/180 for v in found]))
else:zoom=''
s=engine.RenderSettings(width=1280,height=720,fps=FPS,stabilize=True,smooth=False,
                       codec='work',loop_crossfade=CROSSFADE)
duration=engine._normalized_clip(source,base/'normalized.mp4',s,zoom=zoom)
frames=round(duration*FPS);expected=expected_loop_frames(frames)
engine._crossfade_loop(base/'normalized.mp4',base/'native-loop.mp4',duration,s)
limited(['ffmpeg','-y','-i',str(base/'native-loop.mp4'),'-vf','scale=1920:1080:flags=lanczos',
         '-an','-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p',str(base/'loop-master.mp4')])
loop_duration=engine.probe_duration(base/'loop-master.mp4')
if abs(loop_duration-expected/FPS)>1/FPS:raise ValueError('Cyclic master duration mismatch')
limited(['ffmpeg','-y','-stream_loop','-1','-i',str(base/'loop-master.mp4'),'-i',str(base/'audio.wav'),
         '-t','30','-map','0:v:0','-map','1:a:0','-r','24','-c:v','libx264','-preset','fast',
         '-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(base/'preview.mp4')])
check=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(base/'preview.mp4')],capture_output=True,text=True,check=True).stdout)
for kind in ('audio','video'):
 stream=next(v for v in check['streams'] if v['codec_type']==kind)
 if abs(float(stream['duration'])-30)>.05:raise ValueError('Preview duration mismatch')
report=dict(builder_version=VERSION,request_id=rid,source_seconds=duration,source_frames=frames,
    loop_seconds=loop_duration,loop_frames=expected,crossfade_seconds=CROSSFADE,
    full_frame_only=True,local_masks=False,stabilization=True,zoom_correction=bool(measure),
    camera_fit=measure,technical_check='passed',preview_repeat='exact_cyclic_master',
    publication_loop_mode='repeat',publication_crossfade=0,visual_motion_review='PENDING',
    listening_review='PENDING',delivery='HELD_UNTIL_QA',
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    loop_master_sha256=hashlib.sha256((base/'loop-master.mp4').read_bytes()).hexdigest())
(base/'recipe-and-checks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''


def main(rid):
    import cabin_backlog_registry as registry
    if not registry.attempt(rid):raise ValueError('Only staged Cabin sources')
    folder=ROOT/'assets'/rid;folder.mkdir(exist_ok=True)
    source=Path('/opt/marketplace-analytics/studio-downloads')/(rid+'.mp4')
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    report_path=folder/'recipe-and-checks.json'
    if report_path.exists():
        old=json.loads(report_path.read_text())
        if old.get('technical_check')=='passed':
            if old.get('builder_version')!=VERSION:
                raise ValueError('Preserve previous preview; create a repair version instead')
            if old.get('source_sha256')!=source_sha:raise ValueError('Source changed under a frozen version')
            if (folder/'preview.mp4').is_file() and (folder/'loop-master.mp4').is_file():
                if hashlib.sha256((folder/'loop-master.mp4').read_bytes()).hexdigest()!=old['loop_master_sha256']:
                    raise ValueError('Cyclic master changed')
                print(json.dumps(old));return
    prefix='/tmp/'+rid
    def run(args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,**kw)
    run(['docker','exec','relax-factory','mkdir','-p',prefix])
    for src,dst in [(source,prefix+'/source.mp4'),(ROOT/'assets/cabin-approved-fireplace-9.wav',prefix+'/audio.wav'),
                    (ROOT/'cabin_loop_recipe.py','/tmp/cabin_loop_recipe.py')]:
        run(['docker','cp',str(src),'relax-factory:'+dst])
    try:
        result=run(['docker','exec','-i','relax-factory','python','-',rid],input=CODE,timeout=900)
    except subprocess.CalledProcessError as error:
        (folder/'loop-build-error.json').write_text(json.dumps({'error':error.stderr[-5000:],
            'stdout':error.stdout[-1000:],'builder_version':VERSION},ensure_ascii=False,indent=2))
        raise RuntimeError('Cyclic master build failed: '+error.stderr[-1200:]) from error
    report=json.loads(result.stdout)
    report.update(preview=str(folder/'preview.mp4'),loop_master=str(folder/'loop-master.mp4'),
                  audio_source=str(ROOT/'assets/cabin-approved-fireplace-9.wav'))
    for name in ('preview.mp4','loop-master.mp4','normalized.mp4'):
        run(['docker','cp','relax-factory:'+prefix+'/'+name,str(folder/name)])
    report_path.write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
