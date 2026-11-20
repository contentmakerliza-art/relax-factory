"""Measure local template displacement on fixed Cabin 18 geometry, not visual approval."""
import argparse,json,subprocess
from pathlib import Path
import numpy as np


def feature(a):
    a=a.astype(np.float32)
    return a-a.mean()


def locate(template,patch):
    scores=np.empty((7,7))
    for dy in range(7):
        for dx in range(7):
            other=feature(patch[dy:dy+template.shape[0],dx:dx+template.shape[1]])
            scores[dy,dx]=np.mean((other-template)**2)
    iy,ix=np.unravel_index(np.argmin(scores),scores.shape)
    def sub(v,i):
        if not 0<i<len(v)-1:return float(i)
        den=v[i-1]-2*v[i]+v[i+1]
        return i+float((v[i-1]-v[i+1])/(2*den)) if den>0 else float(i)
    return sub(scores[iy],ix)-3,sub(scores[:,ix],iy)-3,float(scores[iy,ix])


def main(request_id,filename='source.mp4'):
    if filename not in ('source.mp4','preview.mp4'):raise ValueError('Unsupported media file')
    path=Path('/tmp')/request_id/filename
    proc=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-i',str(path),'-vf','fps=8,scale=1280:720',
                           '-pix_fmt','gray','-threads','1','-f','rawvideo','-'],stdout=subprocess.PIPE)
    regions={'head':(805,496,94,70),'paws':(833,552,95,30),'wall':(160,20,100,100)}
    if request_id.startswith('cabin22-'):
        regions={'head':(228,568,80,65),'paws':(242,625,65,24),'wall':(370,30,100,100)}
    if request_id.startswith('cabin08-'):
        regions={'head':(520,484,85,62),'paws':(562,526,75,28),'wall':(135,15,100,100)}
    regions['flank']=(900,510,70,45)
    if request_id.startswith('cabin22-'):regions['flank']=(150,580,70,50)
    if request_id.startswith('cabin08-'):regions['flank']=(583,490,60,40)
    templates={};positions={k:[] for k in regions}
    while True:
        raw=bytearray()
        while len(raw)<1280*720:
            chunk=proc.stdout.read(1280*720-len(raw))
            if not chunk:break
            raw.extend(chunk)
        if not raw:break
        if len(raw)!=1280*720:raise ValueError('Incomplete frame')
        frame=np.frombuffer(raw,np.uint8).reshape(720,1280)
        for name,(x,y,w,h) in regions.items():
            if name not in templates:templates[name]=feature(frame[y:y+h,x:x+w])
            positions[name].append(locate(templates[name],frame[y-3:y+h+3,x-3:x+w+3]))
    if proc.wait()!=0:raise ValueError('Decode failed')
    prefix='preview-' if filename=='preview.mp4' else ''
    (path.parent/(prefix+'motion-traces.json')).write_text(json.dumps({'sample_rate':8,'regions':regions,'positions':positions}))
    report={}
    for name,items in positions.items():
        a=np.asarray(items)
        report[name]={'x_range_pixels':float(np.ptp(a[:,0])),'y_range_pixels':float(np.ptp(a[:,1])),
                      'max_match_mse':float(a[:,2].max()),'samples':len(items)}
    (path.parent/(prefix+'head-motion.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');p.add_argument('--filename',default='source.mp4')
    a=p.parse_args();main(a.request_id,a.filename)
