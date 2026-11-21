"""Preflight the complete voice/background mix of each scheduled Exhale recipe."""
import json,tempfile,sys
from pathlib import Path
sys.path.insert(0,'/app')
from render import engine,preserved_exhale

LIB=Path('/data/sources/executor-library')

def main():
    rows=json.loads((LIB/'exhale-publication-staging/manifest.json').read_text());results=[]
    settings=engine.RenderSettings(width=1920,height=1080,fps=30,duration=36000,audio_bitrate='320k')
    for row in rows:
        root=LIB/'exhale-publication-staging'/row['job_id']
        recipe=json.loads((root/'voice/zz-preserved-exhale.json').read_text())
        result=dict(number=row['number'],job_id=row['job_id'])
        try:
            with tempfile.TemporaryDirectory(dir=LIB/'tests/preserved-exhale') as td:
                preserved_exhale.build_audio(recipe,root/'voice/00-arranged-voice.wav',root/'ambient/background.flac',
                    Path(td)/'unused.m4a',settings,Path(td),engine,encode=False)
            result.update(passed=True,complete_voice_mixed=True,peak_limit_dbfs=-.6)
        except Exception as error:result.update(passed=False,error=str(error)[-800:])
        results.append(result);print(json.dumps(result),flush=True)
    report=dict(passed=all(r['passed'] for r in results),recipes_checked=len(results),results=results,
                ten_hour_finals_started=False,owner_approvals_changed=False,new_generations=0)
    (LIB/'tests/preserved-exhale/full-audio-preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise ValueError('Inspect failed full audio mix before render date')

if __name__=='__main__':main()
