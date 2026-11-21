import sys,json,subprocess,pathlib,hashlib,shutil,fcntl
ROOT=pathlib.Path('/opt/relax-codex');sys.path.insert(0,str(ROOT));from cabin_window_snow11 import PARENT,REQUEST
assets=ROOT/'assets'/REQUEST;assets.mkdir(exist_ok=True)
if (assets/'recipe-and-checks.json').exists():
 old=json.loads((assets/'recipe-and-checks.json').read_text())
 if hashlib.sha256((assets/'preview.mp4').read_bytes()).hexdigest()!=old.get('preview_sha256'):raise ValueError('Frozen prototype changed; use a new version')
 print(json.dumps(old));sys.exit(0)
code=r'''
from pathlib import Path
from PIL import Image,ImageDraw
import sys,json,subprocess,hashlib,os
sys.path.insert(0,'/tmp');sys.path.insert(0,'/app');os.environ['OMP_NUM_THREADS']='2'
from cabin_window_snow11 import make_mask,PARENT,REQUEST
from cabin_loop_recipe import VERSION,expected_loop_frames
from render import engine
base=Path('/data/sources/cabin11-window-snow-test');base.mkdir(parents=True,exist_ok=True)
mask=make_mask();mask.save(base/'window-mask.png')
# Diagnostic-only colored view of selected glass; never used in the owner video.
reference=Image.open(base/'reference.png').convert('RGB');colored=Image.new('RGB',reference.size,'#df37a1')
Image.composite(colored,reference,mask.point(lambda v:int(v*.35))).save(base/'mask-placement.png')
source=base/'parent-normalized.mp4';duration=engine.probe_duration(source)
raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss','1','-i',str(base/'snow.mkv'),'-vf','scale=320:180','-frames:v','1','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],capture_output=True,check=True).stdout
if not raw or sum(raw)/len(raw)>40:raise ValueError('Expected sparse gray Snow alpha, not opaque footage')
# Two existing alpha phases increase density; the glass mask blocks all interior pixels.
graph=('[0:v]fps=24,setpts=PTS-STARTPTS,format=yuv420p[bg];'
 '[1:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s1];'
 '[2:v]fps=24,scale=1280:720,format=gray,setpts=PTS-STARTPTS[s2];'
 '[s1][s2]blend=all_mode=lighten,lut=y=\'min(255,val*1.7)\'[dense];'
 '[3:v]format=gray[mask];[dense][mask]blend=all_mode=multiply[alpha];'
 f'color=c=0xf5f8fa:s=1280x720:r=24:d={duration}[white];'
 '[white][alpha]alphamerge[snow];[bg][snow]overlay=shortest=1:format=auto,crop=1184:666:48:27,scale=1280:720:flags=lanczos,format=yuv420p[v]')
cmd=['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(source),'-threads','1','-i',str(base/'snow.mkv'),
 '-threads','1','-ss','11.5','-i',str(base/'snow.mkv'),'-loop','1','-framerate','24','-i',str(base/'window-mask.png'),
 '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-t',str(duration),'-an','-c:v','libx264',
 '-threads','2','-preset','fast','-crf','16','-pix_fmt','yuv420p',str(base/'composed.mp4')]
subprocess.run(cmd,check=True,capture_output=True,text=True)
original=engine._run
def limited(cmd):
 if cmd[0]=='ffmpeg':cmd=cmd[:1]+['-nostdin','-threads','1','-filter_complex_threads','1']+cmd[1:-1]+['-threads','2']+cmd[-1:]
 return original(cmd)
engine._run=limited
settings=engine.RenderSettings(width=1280,height=720,fps=24,codec='work',loop_crossfade=.75,stabilize=False,smooth=False)
engine._crossfade_loop(base/'composed.mp4',base/'native-loop.mp4',duration,settings)
limited(['ffmpeg','-y','-i',str(base/'native-loop.mp4'),'-vf','scale=1920:1080:flags=lanczos','-an','-c:v','libx264','-preset','fast','-crf','16',str(base/'loop-master.mp4')])
limited(['ffmpeg','-y','-stream_loop','-1','-i',str(base/'loop-master.mp4'),'-i',str(base/'audio.wav'),'-t','30','-map','0:v','-map','1:a',
 '-r','24','-c:v','libx264','-preset','fast','-crf','19','-c:a','aac','-b:a','192k','-movflags','+faststart',str(base/'preview.mp4')])
loop=engine.probe_duration(base/'loop-master.mp4')
if abs(loop-expected_loop_frames(round(duration*24))/24)>.05:raise ValueError('Cycle mismatch')
report=dict(builder_version=VERSION,composition_version='window-snow-chair-exclusion-v2',occlusion_policy='sampled-chair-silhouette-union-plus-4-source-pixels',request_id=REQUEST,parent_request_id=PARENT,
 source_seconds=duration,source_frames=round(duration*24),loop_seconds=loop,loop_frames=round(loop*24),crossfade_seconds=.75,
 full_frame_only=True,local_masks=True,mask_scope='exterior_window_glass_only',fireplace_masks=False,window_snow_overlay=True,
 technical_check='passed',frame_border_crop_pixels=[48,27],preview_repeat='exact_cyclic_master',publication_loop_mode='repeat',publication_crossfade=0,
 stabilization='inherited_from_parent',source_sha256=hashlib.sha256((base/'composed.mp4').read_bytes()).hexdigest(),
 preview_sha256=hashlib.sha256((base/'preview.mp4').read_bytes()).hexdigest(),mask_sha256=hashlib.sha256((base/'window-mask.png').read_bytes()).hexdigest(),
 loop_master_sha256=hashlib.sha256((base/'loop-master.mp4').read_bytes()).hexdigest(),snow_generation=False,new_paid_images=0,
 parent_normalized_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),snow_alpha_mean=sum(raw)/len(raw))
(base/'recipe-and-checks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''
with (ROOT/'cabin-backlog/media-check.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 base='/data/sources/cabin11-window-snow-test';subprocess.run(['docker','exec','relax-factory','mkdir','-p',base],check=True)
 snow=next(pathlib.Path('/var/lib/relax-factory/sources/executor-library').rglob('Снег Little Paris — мелкие хлопья — альфа 30 секунд.mkv'))
 files=[(ROOT/'cabin_window_snow.py','/tmp/cabin_window_snow.py'),(ROOT/'cabin_window_snow11.py','/tmp/cabin_window_snow11.py'),(ROOT/'cabin_loop_recipe.py','/tmp/cabin_loop_recipe.py'),
 (ROOT/'assets'/PARENT/'normalized.mp4',base+'/parent-normalized.mp4'),(ROOT/'cabin11-mask-reference.png',base+'/reference.png'),
 (snow,base+'/snow.mkv'),(ROOT/'assets/cabin-approved-fireplace-9.wav',base+'/audio.wav')]
 for src,dst in files:subprocess.run(['docker','cp',str(src),'relax-factory:'+dst],check=True,capture_output=True)
 result=subprocess.run(['docker','exec','-i','relax-factory','python','-'],input=code,capture_output=True,text=True,timeout=900)
 if result.returncode:
  (assets/'build-error.txt').write_text(result.stderr);raise RuntimeError(result.stderr[-2000:])
 report=json.loads(result.stdout)
 for name in ['preview.mp4','loop-master.mp4','recipe-and-checks.json','window-mask.png','mask-placement.png']:
  subprocess.run(['docker','cp','relax-factory:'+base+'/'+name,str(assets/name)],check=True,capture_output=True)
 # The composited 10-second clip is an auditable derived source, not a provider generation.
 target=pathlib.Path('/opt/marketplace-analytics/studio-downloads')/(REQUEST+'.mp4')
 subprocess.run(['docker','cp','relax-factory:'+base+'/composed.mp4',str(target)],check=True,capture_output=True)
 print(json.dumps(report),flush=True)
