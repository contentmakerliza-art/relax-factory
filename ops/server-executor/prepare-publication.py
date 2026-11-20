"""Complete the approved pilot card using factory API; activate after the loop recipe is verified."""
import base64
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import uuid

JOB='20261120-140220-1bed'
WHEN='2026-12-17T22:00'


def call(path, method='GET', values=None, file=None):
    headers={'Authorization':'Basic '+base64.b64encode(('relax:'+os.environ['APP_PASSWORD']).encode()).decode()}
    data=None
    if file:
        boundary=uuid.uuid4().hex;key,file_path,mime=file
        data=b''
        for k,v in (values or {}).items():
            data+=f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        data+=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{file_path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        data+=file_path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        headers['Content-Type']='multipart/form-data; boundary='+boundary
    elif values is not None:
        data=urllib.parse.urlencode(values).encode();headers['Content-Type']='application/x-www-form-urlencoded'
    req=urllib.request.Request('http://127.0.0.1:8000'+path,method=method,data=data,headers=headers)
    with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)


def main():
    recipe=Path(os.environ.get('APP_DATA','/app/data'))/JOB/'codex-publication-recipe.json'
    if not recipe.exists() or not json.loads(recipe.read_text()).get('validated_with_factory_engine'):
        raise ValueError('Loop recipe needs verification; preserve approval and report blocker')
    queue=call('/queue')
    existing=[r for r in queue if r.get('source')==JOB]
    if existing:
        print(json.dumps({'existing':existing},ensure_ascii=False));return
    if any(r.get('user')=='Quiet_Pines' and r.get('publish_at','').startswith(WHEN[:10]) for r in queue):
        raise ValueError('Channel already has a publication on requested date')
    approvals=call('/approvals')
    if not any(r['job_id']==JOB and r['status']=='одобрено' for r in approvals):
        raise ValueError('Exact version is not approved')
    audio=call('/jobs/'+JOB+'/background-audio')
    if not audio.get('seconds',0)>30:
        audio=call('/jobs/'+JOB+'/background-audio','POST',{},
                   ('file',Path('/tmp/cabin-full-fireplace-9.wav'),'audio/wav'))
    values={'source':JOB,'title':'Cozy Winter Library & Crackling Fireplace | Sleeping Cat | 3 Hours',
            'description':'Settle into a warm wooden library with a sleeping cat and a crackling fireplace. Snow falls outside the windows while the room stays calm.\n\nThree hours of fireplace ambience for reading, relaxing and winding down. No music or wind in the audio.\n\nThis scene was created with AI and edited for Quiet Pines Cabin.',
            'tags':'cozy cabin, winter library, crackling fireplace, fireplace sounds, sleeping cat, snowfall, relaxing ambience, quiet pines cabin',
            'publish_at':WHEN,'user':'Quiet_Pines','hours':'3','bitrate':'4',
            'synthetic':'true','draft':'false','render_now':'false'}
    result=call('/queue','POST',values,('cover_file',Path('/tmp/cabin17-cover.jpg'),'image/jpeg'))
    print(json.dumps({'publication':result,'full_audio_seconds':audio['seconds'],
                      'automatic_render_lead_hours':24},ensure_ascii=False))


if __name__=='__main__':main()
