"""Compare preserved owner-approved Exhale preview with its portable rebuild."""
import json,subprocess,hashlib,wave
from pathlib import Path
import numpy as np


def audio(path):
    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-vn','-ar','22050',
        '-ac','1','-f','f32le','-'],check=True,capture_output=True)
    return np.frombuffer(r.stdout,np.float32)


def main():
    data=Path('/data');job=data/'20261119-102030-80a8'
    original=job/json.loads((job/'job.json').read_text())['output']
    rebuilt=next((data/'sources/executor-library/tests/exhale').glob('Exhale to Sleep — 30.11*.mp4'))
    a=audio(original);b=audio(rebuilt);n=min(len(a),len(b))
    correlation=float(np.corrcoef(a[:n],b[:n])[0,1])
    reference=rebuilt.parent/'approved-reference.wav'
    source=rebuilt.with_name(rebuilt.stem+' — source PCM.wav')
    def pcm_hash(path):
        with wave.open(str(path)) as f:
            if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(2,2,48000):
                raise ValueError('PCM format differs')
            return hashlib.sha256(f.readframes(f.getnframes())).hexdigest()
    pcm_identical=pcm_hash(reference)==pcm_hash(source)
    procs=[subprocess.Popen(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(p),
        '-vf','scale=640:360','-pix_fmt','gray','-f','rawvideo','-'],stdout=subprocess.PIPE) for p in [original,rebuilt]]
    diffs=[]
    try:
        while True:
            frames=[]
            for proc in procs:
                frame=proc.stdout.read(640*360)
                if frame and len(frame)!=640*360:raise ValueError('Partial decoded frame')
                frames.append(frame)
            if not any(frames):break
            if not all(frames):raise ValueError('Frame counts differ')
            arrays=[np.frombuffer(f,np.uint8).astype(np.int16) for f in frames]
            diffs.append(float(np.abs(arrays[0]-arrays[1]).mean()))
        for proc in procs:
            if proc.wait()!=0:raise ValueError('Comparison decode failed')
    finally:
        for proc in procs:
            proc.stdout.close()
            if proc.poll() is None:proc.kill();proc.wait()
    result=dict(frames_compared=len(diffs),audio_correlation=correlation,
        max_frame_mean_difference=max(diffs),mean_frame_difference=float(np.mean(diffs)),
        original=str(original),rebuilt=str(rebuilt),listening_performed=False,
        source_pcm_identical=pcm_identical,
        passed=bool(len(diffs)==900 and pcm_identical and correlation>.999 and max(diffs)<1))
    (data/'sources/executor-library/tests/exhale/comparison.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
    if not result['passed']:raise ValueError('Portable rebuild differs from approved preview')


if __name__=='__main__':main()
