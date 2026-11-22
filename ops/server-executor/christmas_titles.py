"""Owner's seasonal title policy; only three winter channels, never Exhale."""
import re
CHANNELS={'Little Paris Jazz Cafe','Quiet Pines Cabin','Mountain View Cafe'}
VERSION='2026-11-21-christmas-first'

def title_for(channel,title):
    if channel not in CHANNELS:return title
    text=re.sub(r'[❄🎄☕\ufe0f]','',title)
    text=re.sub(r'\bChristmas\b','',text,flags=re.I)
    text=re.sub(r'\s+',' ',text).strip(' |—-')
    text=re.sub(r'Jazz (?=(?:Soft|Winter|Snowy|Cozy|Nyhavn|Peaceful|Gentle)\b)', 'Jazz | ', text)
    if channel=='Quiet Pines Cabin':
        parts=[p.strip() for p in text.split('|')]
        if parts[0].startswith('Crackling') and len(parts)>1:
            scene=parts[1].split(',')[0].strip()
        else:
            scene=re.split(r'\s*&\s*(?:Sleeping Cat|Crackling|Gentle)',parts[0],flags=re.I)[0]
        scene=re.sub(r'^Snowy\s+','',scene,flags=re.I)
        scene=re.sub(r'^in the\s+','',scene,flags=re.I)
        sound='Wood Stove' if 'wood stove' in text.lower() else 'Fireplace'
        result=f'Christmas in the {scene} | {sound} & Snowfall, Sleeping Cat | 3 Hours'
    else:result='Christmas '+text
    if len(result)>100:
        result=re.sub(r'\s+for (?:Work & Reading|Reading & Focus|Work & Relaxation|Work & Study|Work & Reading|Reading & Work)', '', result)
    if len(result)>100:result=result[:97].rsplit(' ',1)[0].rstrip(' |,—-')+'…'
    if len(result)>100 or not result.startswith('Christmas ') or result.lower().count('christmas')!=1:
        raise ValueError('Invalid seasonal title')
    return result
