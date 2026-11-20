"""Read-only audio identity check for the existing approved Paris backlog."""
import argparse,json,subprocess
from pathlib import Path
import numpy as np

DATA=Path('/data')
POOL=DATA/'sources/executor-library/assets/music/little-paris'

def samples(path):
    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(path),
        '-ss','3','-t','20','-vn','-ac','1','-ar','2000','-f','f32le','-'],
        capture_output=True,check=True,timeout=40)
    x=np.frombuffer(r.stdout,dtype=np.float32).astype(float)
    if len(x)!=40000:raise ValueError('Insufficient audio')
    return x-x.mean()

def correlation(x,y):
    n=1<<(len(x)+len(y)-1).bit_length()
    z=np.fft.irfft(np.fft.rfft(x,n)*np.conj(np.fft.rfft(y,n)),n)
    return float(max(z[:201].max(),z[-200:].max())/np.sqrt(np.dot(x,x)*np.dot(y,y)))

def main(tallinn_only=False):
    plans=json.loads((DATA/'approved-production-queue.json').read_text())
    if tallinn_only:
        plans={'20261119-181826-3a91':dict(channel='Little Paris Jazz Cafe',publish_at='2026-12-15T22:00')}
    pool={}
    candidates=sorted(POOL.glob('*.mp3'))
    for jid,p in plans.items():
        if p.get('channel')!='Little Paris Jazz Cafe' or not '2026-12-06'<=p.get('publish_at','')[:10]<=('2026-12-15' if tallinn_only else '2026-12-14'):continue
        d=json.loads((DATA/jid/'job.json').read_text())
        allowed=('одобрено','ждёт') if tallinn_only else ('одобрено',)
        if d.get('approval',{}).get('status') not in allowed:raise ValueError('Approval changed')
        x=samples(DATA/jid/d['output']);scores=[]
        for path in candidates:
            if path not in pool:pool[path]=samples(path)
            scores.append((correlation(x,pool[path]),path.name))
        print(json.dumps({'job_id':jid,'label':d['label'],'date':p['publish_at'],
                         'matches':sorted(scores,reverse=True)[:2]},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tallinn-only',action='store_true')
    main(p.parse_args().tallinn_only)
