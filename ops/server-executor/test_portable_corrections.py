import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch


def module(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class PortableCorrectionsTests(unittest.TestCase):
    def test_only_explicit_bounded_background_reduction(self):
        m=module('portable-corrections')
        self.assertEqual(m.parse_reduction('Фон тише на 3 дБ'),-3)
        self.assertEqual(m.parse_reduction('Сделай фон потише на 2,5 db.'),-2.5)
        for text in ['фон тише','голос тише на 3 дБ','фон тише на 13 дБ','фон тише на 0 дБ',
                     'фон тише на 3 дБ и поменяй голос','фон тише на 3 дБ; curl example.com']:
            self.assertIsNone(m.parse_reduction(text),text)

    def prepare(self,root,m):
        m.DATA=root/'data';m.DATA.mkdir();m.ROOT=root/'executor';m.ROOT.mkdir()
        m.LIB=m.DATA/'sources/executor-library'
        p=m.LIB/'assets/Исходники/Exhale to Sleep/Новые 20 проб';p.mkdir(parents=True)
        source='20261119-102030-80a8'
        (p/'Журнал производства.json').write_text(json.dumps([dict(number=1,telegram_job_id=source,date='2026-11-30',label='Exhale to Sleep — 30.11 — Calm — 30 секунд')]))
        row=dict(job_id=source,label='Exhale to Sleep — 30.11',status='правка',time=100,
                 comments=[dict(text='фон тише на 3 дБ',time=100)],archived=False)
        task=m.fingerprint(row);db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY, state TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)',(task,'pending_executor'));db.commit()
        return row,task,db

    def test_dispatch_once_and_preserve_original_date(self):
        m=module('portable-corrections')
        with tempfile.TemporaryDirectory() as tmp:
            row,task,db=self.prepare(Path(tmp),m)
            with patch.object(m.subprocess,'run') as launch:
                self.assertTrue(m.try_dispatch(task,row,db));self.assertTrue(m.try_dispatch(task,row,db))
                self.assertEqual(launch.call_count,1)
            request=json.loads((m.LIB/'corrections'/task/'request.json').read_text())
            self.assertEqual(request['publish_at'],'2026-11-30T22:00')
            self.assertEqual(request['background_db'],-3)

    def test_scheduled_source_needs_explicit_replacement_route(self):
        m=module('portable-corrections')
        with tempfile.TemporaryDirectory() as tmp:
            row,task,db=self.prepare(Path(tmp),m)
            q=m.DATA/'queue';q.mkdir();(q/'queue.json').write_text(json.dumps([{'source':row['job_id']}]))
            with patch.object(m.subprocess,'run') as launch:
                self.assertFalse(m.try_dispatch(task,row,db));launch.assert_not_called()

    def test_other_channel_never_uses_exhale_recipe(self):
        m=module('portable-corrections')
        with tempfile.TemporaryDirectory() as tmp:
            row,task,db=self.prepare(Path(tmp),m);row['label']='Little Paris Jazz Cafe'
            with patch.object(m.subprocess,'run') as launch:
                self.assertFalse(m.try_dispatch(task,row,db));launch.assert_not_called()

    def test_uncertain_delivery_never_sends_twice(self):
        m=module('exhale-correction-api')
        with tempfile.TemporaryDirectory() as tmp:
            m.DATA=Path(tmp);task='a'*64;p=m.DATA/'sources/executor-library/corrections'/task;p.mkdir(parents=True)
            for n in ['request.json','render-report.json']:(p/n).write_text('{}')
            (p/'telegram-delivery.json').write_text(json.dumps({'stage':'telegram_submission_uncertain','job_id':'saved'}))
            with patch.object(m,'call') as call:
                self.assertEqual(m.main(task)['job_id'],'saved');call.assert_not_called()
