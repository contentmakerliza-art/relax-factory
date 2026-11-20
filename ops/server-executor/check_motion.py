"""Numerical full-sequence check; complements visual review, not a visual approval."""
import json
import subprocess
import numpy as np
path='/tmp/cabin17-fullframe-v2-20261120/preview.mp4'
r=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',path,'-vf','scale=640:360',
                  '-pix_fmt','gray','-f','rawvideo','-threads','1','-'],capture_output=True,check=True)
f=np.frombuffer(r.stdout,np.uint8).reshape(-1,360,640).astype(np.float32)
d=np.abs(f[1:]-f[:-1]);means=d.mean(axis=(1,2));worst=np.argsort(means)[-8:]
print(json.dumps({'decoded_frames':len(f),'mean_difference':float(means.mean()),
                 'max_difference':float(means.max()),
                 'worst_frame_times':[(int(i+1),round(float(means[i]),3)) for i in worst],
                 'wall_max':float(d[:,20:140,15:95].mean(axis=(1,2)).max()),
                 'cat_max':float(d[:,250:290,130:205].mean(axis=(1,2)).max())}))
