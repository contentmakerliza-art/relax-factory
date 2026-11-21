from pathlib import Path
import subprocess,json
ROOT=Path('/opt/relax-codex');TARGET='cabin20-trimmed-v15-20261122';PARENT='cabin20-fixed-v15-20261121'
assets=ROOT/'assets'/TARGET;assets.mkdir(exist_ok=True)
code=r'''
import subprocess,json,numpy as np
from pathlib import Path
base=Path('/data/sources/cabin20-seam-trim');source=base/'parent.mp4'
raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(source),'-vf','select=not(mod(n\\,12)),format=gray','-fps_mode','vfr','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],capture_output=True,check=True).stdout
frames=np.frombuffer(raw,np.uint8).reshape(-1,720,1280)
boxes=[(850,160,54,75),(854,420,46,75),(180,170,70,70),(420,150,90,80)]
rows=[]
for start in range(4):
 first=frames[start].astype(float);last=frames[start+17].astype(float)
 scores=[]
 for x,y,w,h in boxes:
  a=first[y:y+h,x:x+w];b=last[y:y+h,x:x+w]
  scores.append(float(np.mean(((a-a.mean())-(b-b.mean()))**2)))
 rows.append(dict(start_seconds=start*.5,retained_seconds=8.5,anchor_mse=scores,score=float(np.median(scores))))
best=min(rows,key=lambda row:row['score'])
subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(source),'-vf',f"trim=start={best['start_seconds']}:duration=8.5,setpts=PTS-STARTPTS",'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','15',str(base/'normalized.mp4')],check=True,capture_output=True)
report=dict(method='select-8.5-second-native-segment-with-lowest-rigid-anchor-endpoint-error',candidates=rows,selected=best,new_generation=False,extra_camera_warp=False)
(base/'segment-selection.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''
base='/data/sources/cabin20-seam-trim'
subprocess.run(['docker','exec','relax-factory','mkdir','-p',base],check=True,capture_output=True)
subprocess.run(['docker','cp',str(ROOT/'assets'/PARENT/'normalized.mp4'),'relax-factory:'+base+'/parent.mp4'],check=True,capture_output=True)
p=subprocess.run(['docker','exec','-i','relax-factory','python','-'],input=code,capture_output=True,text=True,timeout=180)
(assets/'selection-run.log').write_text(p.stdout+p.stderr)
if p.returncode:raise RuntimeError(p.stderr[-1800:])
for name in ['normalized.mp4','segment-selection.json']:subprocess.run(['docker','cp','relax-factory:'+base+'/'+name,str(assets/name)],check=True,capture_output=True)
print(p.stdout,flush=True)
