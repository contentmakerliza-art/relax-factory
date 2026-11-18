"""Durable intake queue: every approval survives missing render/upload setup.

This queue never publishes by itself. Complete, approved entries can be handed
to the existing publication queue; incomplete entries remain visible, with dates.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json, os, threading, time
from fastapi import Depends, Form, HTTPException

CHANNELS = {
    'Little Paris Jazz Cafe': {'hours':3, 'profile':'', 'start':'2026-11-22'},
    'Quiet Pines Cabin': {'hours':3, 'profile':'Quiet_Pines', 'start':'2026-11-26'},
    'Exhale to Sleep': {'hours':10, 'profile':'Exhale_to_Sleep', 'start':'2026-11-30'},
    'Mountain View Cafe': {'hours':3, 'profile':'', 'start':''},
}

# Verified in YouTube Studio on 18 November: these must not be scheduled twice.
STUDIO = {
 '20261115-114638-f423':'2026-11-16T22:00',
 '20261115-123230-16a9':'2026-11-17T22:00',
 '20261115-125117-dfda':'2026-11-18T22:00',
 '20261115-125143-e513':'2026-11-19T22:00',
 '20261115-125144-57f0':'2026-11-20T22:00',
 '20261115-125320-18cc':'2026-11-21T22:00',
}

def channel_of(label):
    label=label.casefold().replace('café','cafe')
    return next((name for name in CHANNELS if name.casefold() in label),'')

class ApprovalQueue:
    def __init__(self, data, jobs, publications, source_dir, label, now, on_ready=None):
        self.data=Path(data);self.jobs=jobs;self.publications=publications
        self.source_dir=source_dir;self.label=label;self.now=now
        self.path=self.data/'approved-production-queue.json';self.lock=threading.RLock();self.on_ready=on_ready
        try:self.rows=json.loads(self.path.read_text())
        except FileNotFoundError:self.rows={}
        # Fail closed on corrupt persisted state, never silently replace it.
        if not isinstance(self.rows,dict):raise ValueError('Invalid approval queue file')

    def save(self):
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.rows,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,self.path)

    def sync(self):
        with self.lock:
            before=json.dumps(self.rows,ensure_ascii=False,sort_keys=True)
            queued={x['source']:x for x in self.publications}
            taken={name:{x['publish_at'][:10] for x in self.publications if x.get('channel')==name} for name in CHANNELS}
            for row in self.rows.values():
                if row.get('channel') in taken and row.get('publish_at'):taken[row['channel']].add(row['publish_at'][:10])
            # Oldest first: future approvals append to the channel's last day.
            ordered=sorted(list(self.jobs.items()),key=lambda pair:((pair[1].get('approval') or {}).get('time',0),pair[0]))
            for source,info in ordered:
                approval=info.get('approval') or {}
                if not approval:continue
                if approval.get('status')!='одобрено':
                    if source in self.rows:self.rows[source].update(status='Возвращено на правку',blocker='Нужна новая одобренная версия')
                    continue
                row=self.rows.get(source)
                if row is None:
                    channel=channel_of(self.label(info))
                    row={'source':source,'label':self.label(info),'channel':channel,'publish_at':'','title':'','description':'','tags':'','profile':CHANNELS.get(channel,{}).get('profile',''),'hours':CHANNELS.get(channel,{}).get('hours',3),'approval_time':approval.get('time'),'created':self.now().isoformat(),'history':[{'event':'approved','at':approval.get('time')}],'status':'Принят после одобрения','blocker':''}
                    self.rows[source]=row
                    if channel and source not in queued and source not in STUDIO:
                        future=sorted(d for d in taken[channel] if d>=self.now().strftime('%Y-%m-%d'))
                        start=CHANNELS[channel]['start'] or (self.now()+timedelta(days=1)).strftime('%Y-%m-%d')
                        day=max(datetime.fromisoformat(start).date(),self.now().date()+timedelta(days=1))
                        if future:day=max(day,datetime.fromisoformat(future[-1]).date()+timedelta(days=1))
                        while day.isoformat() in taken[channel]:day+=timedelta(days=1)
                        row['publish_at']=day.isoformat()+'T22:00';taken[channel].add(day.isoformat())
                if source in STUDIO:
                    row.update(publish_at=STUDIO[source],status='Уже загружен в YouTube Studio',blocker='',publication_id='studio:'+source)
                elif source in queued:
                    q=queued[source];row.update(channel=q.get('channel') or row['channel'],publish_at=q['publish_at'],status='Очередь публикаций: '+q['status'],blocker=q.get('error',''),publication_id=q['id'])
                elif not row['channel']:row.update(status='Нужно проверить старое одобрение',blocker='Канал не указан в названии; повторно публиковать автоматически нельзя')
                else:
                    visual=self.source_dir(source,'visual');tracks=self.source_dir(source,'tracks');ambient=self.source_dir(source,'ambient')
                    missing=[]
                    if not visual:missing.append('нет исходного клипа для длинной сборки')
                    if not tracks and not ambient:missing.append('нет полного набора звука')
                    if row['channel']=='Little Paris Jazz Cafe' and not tracks:missing.append('нужен альбом полных треков, не 30-секундный отрывок')
                    if not row.get('profile'):missing.append('не подключена автоматическая публикация канала')
                    if not row.get('title'):missing.append('нужно оформить название и описание')
                    row.update(status='Ожидает подготовки' if missing else 'Готов к очереди публикаций',blocker='; '.join(missing))
                    if not missing and self.on_ready and time.time()-row.get('last_attempt',0)>900:
                        row['last_attempt']=time.time()
                        try:
                            publication=self.on_ready(row)
                            row.update(status='Очередь публикаций: '+publication['status'],publication_id=publication['id'],blocker='')
                            row['history'].append({'event':'publication_queued','at':self.now().isoformat(),'id':publication['id']})
                        except Exception as error:
                            row.update(status='Остановлен перед постановкой',blocker=str(getattr(error,'detail',error))[:500])
            # Source deletion does not erase a recorded approval or its reserved date.
            for source,row in self.rows.items():
                if source not in self.jobs and source not in queued and row['status']!='Возвращено на правку':row.update(status='Нужна проверка архива',blocker='Проба удалена с сервера; одобрение и дата сохранены')
            if before!=json.dumps(self.rows,ensure_ascii=False,sort_keys=True):self.save()
            return sorted(self.rows.values(),key=lambda x:(x.get('publish_at') or '9999',x['source']))

    def plan(self, source, channel, publish_at, title, description, tags, profile, hours):
        with self.lock:
            self.sync()
            if source not in self.rows:raise ValueError('В очереди нет одобренной пробы')
            if channel not in CHANNELS:raise ValueError('Выберите канал')
            if not 0<hours<=12:raise ValueError('Длина должна быть от 0 до 12 часов')
            when=datetime.fromisoformat(publish_at)
            if when.date()<self.now().date():raise ValueError('Дата уже прошла')
            if any(x['source']!=source and x.get('channel')==channel and x.get('publish_at','')[:10]==publish_at[:10] and x.get('status')!='Возвращено на правку' for x in self.rows.values()):raise ValueError('На эту дату уже есть выпуск канала')
            row=self.rows[source];row.update(channel=channel,publish_at=publish_at,title=title,description=description,tags=tags,profile=profile,hours=hours,last_attempt=0)
            row['history'].append({'event':'plan_updated','at':self.now().isoformat(),'publish_at':publish_at})
            self.save();self.sync();return dict(row)

def install(app, data, jobs, publications, source_dir, label, now, auth, on_ready=None):
    queue=ApprovalQueue(data,jobs,publications,source_dir,label,now,on_ready)
    @app.get('/production',dependencies=[Depends(auth)])
    def read_production():return queue.sync()
    @app.post('/production/{source}/plan',dependencies=[Depends(auth)])
    def plan_production(source:str,channel:str=Form(...),publish_at:str=Form(...),title:str=Form(''),description:str=Form(''),tags:str=Form(''),profile:str=Form(''),hours:float=Form(3)):
        try:return queue.plan(source,channel,publish_at,title,description,tags,profile,hours)
        except ValueError as error:raise HTTPException(400,str(error))
    def reconcile():
        try:queue.sync()
        except Exception:
            # A failure is retried by GET /production and must not affect the bot.
            import logging;logging.exception('Cannot reconcile approved production queue')
    reconcile()
    return reconcile
