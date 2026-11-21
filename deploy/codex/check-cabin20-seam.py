"""Compare static window-edge sharpness at old and corrected whole-frame seams."""
from pathlib import Path
import subprocess,json
ROOT=Path('/opt/relax-codex');rid='cabin20-snow3-v15-20261122'
code=r'''
import subprocess,json,numpy as np
from pathlib import Path
sys_path='/tmp'
import sys;sys.path.insert(0,sys_path)
from cabin_window_snow import transform_box
base=Path('/data/sources/cabin20-seam-check')
boxes=[transform_box([850,170,54,75]),transform_box([854,420,46,75]),transform_box([1018,200,24,60])]
def measure(path,fade):
 p=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-vf','scale=1280:720,format=gray','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],stdout=subprocess.PIPE)
 values=[]
 while True:
  raw=bytearray()
  while len(raw)<1280*720:
   v=p.stdout.read(1280*720-len(raw))
   if not v:break
   raw.extend(v)
  if not raw:break
  if len(raw)!=1280*720:raise ValueError('Truncated seam frame')
  f=np.frombuffer(raw,np.uint8).reshape(720,1280).astype(float)
  energies=[]
  for x,y,w,h in boxes:
   a=f[y:y+h,x:x+w];energies.append(float(np.mean(np.diff(a,axis=0)**2)+np.mean(np.diff(a,axis=1)**2)))
  values.append(energies)
 if p.wait()!=0:raise ValueError('Seam decode failed')
 v=np.asarray(values);baseline=np.median(v[12:-fade-6],axis=0)
 ratio=np.mean(v[-fade:]/baseline,axis=1)
 return dict(frames=len(v),crossfade_frames=fade,minimum_relative_edge_energy=float(ratio.min()),median_relative_edge_energy=float(np.median(ratio)),seam_energy_by_frame=ratio.tolist())
old=measure(base/'old.mp4',18);new=measure(base/'new.mp4',6)
# This screen compares rigid edges only; it does not prove real-time playback.
result=dict(previous=old,corrected=new,metric='relative-static-window-gradient-energy',
 acceptable_for_owner_preview=new['minimum_relative_edge_energy']>=min(.9,old['minimum_relative_edge_energy']-.02),
 limitations='Numerical static-edge screen; owner still checks perceived seam and fire motion.')
print(json.dumps(result))
'''
base='/data/sources/cabin20-seam-check'
subprocess.run(['docker','exec','relax-factory','mkdir','-p',base],check=True,capture_output=True)
for src,dst in [(ROOT/'assets/cabin20-snow2-v15-20261122/loop-master.mp4',base+'/old.mp4'),(ROOT/'assets'/rid/'loop-master.mp4',base+'/new.mp4'),(ROOT/'cabin_window_snow.py','/tmp/cabin_window_snow.py')]:subprocess.run(['docker','cp',str(src),'relax-factory:'+dst],check=True,capture_output=True)
p=subprocess.run(['docker','exec','-i','relax-factory','python','-'],input=code,capture_output=True,text=True,timeout=180)
if p.returncode:raise RuntimeError(p.stderr[-1500:])
report=json.loads(p.stdout);(ROOT/'assets'/rid/'seam-edge-check.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
if not report['acceptable_for_owner_preview']:raise ValueError('Seam edge screen needs inspection before delivery')
