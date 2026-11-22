"""Seasonal public metadata derived from the episode's actual scene and soundtrack.

Research notes and audio licenses remain internal; no keyword stuffing or claims
about competitors' private tags, search volume, retention, or guaranteed rankings.
"""
import re
VERSION='2026-11-21-seasonal-keywords-v1'
CHANNELS={'Little Paris Jazz Cafe','Quiet Pines Cabin','Mountain View Cafe'}
CITIES=['Paris','Edinburgh','Amsterdam','Lucerne','Kraków','Krakow','Copenhagen','Stockholm','Innsbruck','Budapest','Riga','Bergen','Ljubljana','Graz','Helsinki','Lyon','Bruges','Strasbourg','Vienna','Annecy','Luxembourg','Tallinn','Ghent','Zurich','Bologna','Munich','Colmar','Heidelberg','Dijon']
BASE={
'Little Paris Jazz Cafe':['christmas cafe ambience','christmas coffee shop','winter cafe jazz','cozy cafe jazz','coffee shop ambience','soft instrumental jazz','jazz for reading','jazz for studying','jazz for work','relaxing jazz music','snowy cafe ambience','winter coffee shop','cozy christmas ambience','3 hour jazz','little paris jazz cafe'],
'Quiet Pines Cabin':['christmas cabin ambience','cozy christmas fireplace','crackling fireplace sounds','fireplace sounds no music','sleeping cat ambience','snowy cabin ambience','winter cabin','cozy winter ambience','fireplace for reading','fireplace for studying','relaxing fireplace','wood fire sounds','3 hour fireplace','quiet pines cabin'],
'Mountain View Cafe':['christmas cafe ambience','christmas fireplace','snowy mountain cafe','mountain cafe ambience','cozy winter cafe','crackling fireplace sounds','fireplace ambience no music','alpine cafe ambience','winter mountain ambience','fireplace for reading','study ambience no talking','relaxing fireplace sounds','cozy christmas ambience','3 hour fireplace','mountain view cafe']}


def clean_public(text):
    text=text.replace('\r\n','\n')
    lines=[]
    for line in text.splitlines():
        if re.search(r'pixabay|^Fireplace audio:|^Audio credit',line,re.I):continue
        line=re.sub(r'[^.!?\n]*(?:AI-created|AI-generated|created with AI|created using AI)[^.!?\n]*[.!?]?', '',line,flags=re.I)
        line=re.sub(r'https?://\S+','',line)
        if line.strip():lines.append(line.strip())
        elif lines and lines[-1]!='':lines.append('')
    return '\n'.join(lines).strip()


def scene_of(channel,title):
    scene=title.split('|')[0].strip()
    scene=re.sub(r'^Christmas(?: in (?:the|a))?\s+','',scene,flags=re.I)
    if channel=='Little Paris Jazz Cafe':
        return next((city for city in CITIES if re.search(r'\b'+re.escape(city)+r'\b',title,re.I)),scene)
    if channel=='Mountain View Cafe':
        for needle,term in [('Dolomites','Dolomites'),('Cable Car','mountain cable car'),('Forest','winter forest cafe'),('Lake','snowy mountain lake'),('Terrace','snowy mountain terrace'),('Alpine Village','snowy alpine village'),('Mountain Village','snowy mountain village')]:
            if needle.lower() in scene.lower():return term
    scene=re.sub(r'\s*&\s*Sleeping Cat.*','',scene,flags=re.I)
    return scene


def description_for(channel,title,old=''):
    if channel not in CHANNELS:return old
    clean=clean_public(old)
    closing='Explore more quiet winter scenes with '+channel+'.'
    if closing in clean:return clean
    scene=scene_of(channel,title)
    if channel=='Little Paris Jazz Cafe':
        opening=(f'Enjoy 3 hours of Christmas café ambience in a snowy scene inspired by {scene}, with soft instrumental jazz for reading, studying and quiet work. This winter coffee shop ambience pairs gentle café jazz with a peaceful view of falling snow.\n\n')
        # Preserve the episode's original factual opening, without technical boilerplate.
        context=clean.split('\n\n')[0] if clean else ''
        if context and len(context)<650:opening+=context+'\n\n'
        body=('Let this cozy Christmas café atmosphere accompany a focused study session, an afternoon with a book, journaling or working from home. The instrumental soundtrack has no vocals or spoken commentary, leaving room for your own thoughts while the snowy street provides an unhurried winter backdrop.\n\n'
          'Use the relaxing jazz music as background listening for a slow coffee break, creative work or winding down in the evening. Keep the volume comfortable and enjoy a winter café setting without conversation. The holiday mood comes from the scene and its warm, gentle jazz atmosphere.\n\n'
          'This three-hour video is intended as a calm backdrop for reading, work and relaxation. Watch the snowfall or let the café jazz play while you settle into your own routine.\n\n')
        hashes='#ChristmasCafe #CafeJazz #WinterAmbience'
    elif channel=='Quiet Pines Cabin':
        opening=(f'Enjoy 3 hours of cozy Christmas cabin ambience in the {scene}, with crackling fireplace sounds, a sleeping cat and snowfall outside. This winter cabin scene offers fireplace ambience with no music, no talking and no vocals.\n\n')
        body=('A warm hearth and a peacefully sleeping cat give the room a quiet, sheltered feeling while the winter landscape remains beyond the windows. Settle into this snowy cabin atmosphere for an evening with a book, an unhurried study session or a break from a busy day.\n\n'
          'The soundtrack is fireplace crackle only. Falling snow is part of the visual scene; no wind or blizzard sound is added. Let the wood fire sounds accompany reading, writing, journaling or quiet work, with a comfortable listening volume that suits your room.\n\n'
          'Choose this Christmas fireplace ambience when you want a cozy winter background without a musical soundtrack or conversation. The three-hour format gives you time to work through a chapter, enjoy a slow evening or wind down before bed while the fire and snowy view remain on screen.\n\n'
          'This three-hour video is intended as a calm backdrop for reading, work and relaxation. Enjoy the sleeping cat, warm hearth and outdoor snowfall at your own pace.\n\n')
        hashes='#ChristmasAmbience #FireplaceSounds #CozyCabin'
    else:
        opening=(f'Enjoy 3 hours of Christmas mountain café ambience with crackling fireplace sounds, snowy mountain scenery and no music or talking. The {scene} setting brings together a warm hearth and a peaceful winter view.\n\n')
        context=clean.split('\n\n')[1:2]
        if context and len(context[0])<650:opening+=context[0]+'\n\n'
        body=('Let this cozy winter café ambience play while you read, study, journal or work from home. The relaxing fireplace sounds offer a simple background for quiet focus, a slow coffee break or an unhurried evening indoors.\n\n'
          'The soundtrack contains fireplace crackle only. Snowfall is part of the view, with no added wind, blizzard sound, music or conversation. Keep the volume at a comfortable level and enjoy the contrast between the warm café and the snowy mountain landscape.\n\n'
          'Choose this Christmas fireplace ambience for a peaceful reading corner, a long study session or winding down before bed. The three-hour format lets the mountain café atmosphere accompany your own routine without a spoken story or musical soundtrack.\n\n'
          'This three-hour video is intended as a calm backdrop for reading, work and relaxation.\n\n')
        hashes='#ChristmasCafe #FireplaceAmbience #MountainViewCafe'
    # Preserve genuine existing track timestamps, never invent them.
    chapters=[line for line in clean.splitlines() if re.match(r'^\d{1,2}:\d{2}(?::\d{2})?\s',line)]
    result=opening+body+closing
    if chapters:result+='\n\nTracklist\n'+'\n'.join(chapters)
    result+='\n\n'+hashes
    if len(result)>5000:raise ValueError('Description exceeds YouTube limit')
    return result


def tags_for(channel,title):
    if channel not in CHANNELS:return []
    scene=scene_of(channel,title).lower()
    scene=re.sub(r'[^\w\s-]','',scene)
    scene=' '.join(scene.split())
    specifics=([scene+' cafe jazz',scene+' winter ambience'] if channel=='Little Paris Jazz Cafe'
               else [scene+' ambience',scene+' fireplace'])
    candidates=specifics+BASE[channel]
    tags=[]
    for tag in candidates:
        if not tag or len(tag)>65 or tag in tags:continue
        proposed=tags+[tag]
        # Conservatively include separator and quote overhead for multiword tags.
        cost=sum(len(t)+2 for t in proposed)+max(0,len(proposed)-1)
        if cost<=490:tags=proposed
    return tags
