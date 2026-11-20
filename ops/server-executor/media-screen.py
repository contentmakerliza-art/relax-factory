"""Stream numerical frame checks with two frames in memory; compare approved audio."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import numpy as np


def main(request_id):
    if not re.fullmatch('[a-z0-9-]{16,80}',request_id):raise ValueError('Bad ID')
    base=Path('/tmp')/request_id
    p=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-i',str(base/'preview.mp4'),
        '-vf','scale=640:360','-pix_fmt','gray','-threads','1','-f','rawvideo','-'],stdout=subprocess.PIPE)
    previous=None;values=[];count=0
    try:
        while True:
            raw=bytearray()
            while len(raw)<640*360:
                part=p.stdout.read(640*360-len(raw))
                if not part:break
                raw.extend(part)
            if not raw:break
            if len(raw)!=640*360:raise ValueError('Truncated frame')
            current=np.frombuffer(raw,np.uint8).reshape(360,640).astype(np.int16)
            if previous is not None:values.append(float(np.abs(current-previous).mean()))
            previous=current;count+=1
        if p.wait()!=0:raise ValueError('Video decode failed')
    finally:
        p.stdout.close()
        if p.poll() is None:p.kill();p.wait()
    def audio(name):
        r=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(base/name),'-t','30',
            '-vn','-ar','22050','-ac','1','-f','f32le','-'],capture_output=True,check=True)
        return np.frombuffer(r.stdout,np.float32)
    a=audio('audio.wav');b=audio('preview.mp4');n=min(len(a),len(b))
    correlation=float(np.corrcoef(a[:n],b[:n])[0,1])
    report={'frames':count,'max_adjacent_frame_difference':max(values),
            'mean_adjacent_frame_difference':float(np.mean(values)),
            'audio_correlation':correlation,'audio_peak':float(np.abs(b).max()),
            'visual_review_required':True,'listening_performed':False}
    # Reject gross technical failures. A passing screen is not visual approval.
    report['technical_screen_passed']=bool(count==720 and correlation>.99 and report['audio_peak']<.99 and np.isfinite(correlation))
    (base/'media-screen.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');main(p.parse_args().request_id)
