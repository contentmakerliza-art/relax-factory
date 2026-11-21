"""Frozen Exhale recipes must fail closed when an input or timeline changes."""
import importlib.util,json,tempfile,unittest,wave
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('preserved',Path(__file__).parents[2]/'render/preserved_exhale.py')
# deploy/codex -> repository/render
if not spec.loader.path.endswith('/render/preserved_exhale.py'):raise RuntimeError('Unexpected module')
preserved=importlib.util.module_from_spec(spec);spec.loader.exec_module(preserved)

class PreservedExhaleTests(unittest.TestCase):
    def fixture(self,root):
        voice_dir=root/'voice';ambient=root/'ambient';voice_dir.mkdir();ambient.mkdir()
        voice=voice_dir/'00-arranged-voice.wav'
        with wave.open(str(voice),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000);f.writeframes(bytes(61*48000*4))
        font=voice_dir/'font.ttf';font.write_bytes(b'preserved font')
        bg=ambient/'background.flac';bg.write_bytes(b'preserved background')
        entry=lambda p:dict(name=p.name,sha256=preserved.digest(p))
        recipe=dict(schema=1,kind='exhale-preserved-v1',voice=entry(voice),font=entry(font),
            background=entry(bg),voice_seconds=61,background_gain=.05,after_gain=1,
            background_offset=0,rise=50,phases=[[16,90,0,1,'inhale']])
        (voice_dir/preserved.MARKER).write_text(json.dumps(recipe))
        job=SimpleNamespace(voice=voice,ambient=[bg],tracks=[])
        settings=SimpleNamespace(duration=36000,width=1920,height=1080,fps=30,logo='')
        return job,settings,recipe

    def test_full_intro_and_ten_hours_are_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));*_,length=preserved.validate(job,s)
            self.assertEqual(length,82)

    def test_thirty_second_clip_cannot_be_used_as_full_final(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));s.duration=30
            with self.assertRaises(ValueError):preserved.validate(job,s)

    def test_changed_voice_is_not_realigned_or_normalized(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));job.voice.write_bytes(b'changed voice')
            with self.assertRaisesRegex(ValueError,'source missing or changed'):preserved.validate(job,s)

    def test_incomplete_fade_timeline_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));r['phases']=[[16,70,0,1,'inhale']]
            (job.voice.parent/preserved.MARKER).write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'complete fade'):preserved.validate(job,s)

    def test_source_path_cannot_escape_input_directory(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));r['voice']['name']='../outside.wav'
            (job.voice.parent/preserved.MARKER).write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'invalid input name'):preserved.validate(job,s)

    def test_last_approved_background_offset_still_has_full_opening(self):
        with tempfile.TemporaryDirectory() as d:
            job,s,r=self.fixture(Path(d));r['background_offset']=132
            (job.voice.parent/preserved.MARKER).write_text(json.dumps(r))
            self.assertEqual(preserved.validate(job,s)[0]['background_offset'],132)

if __name__=='__main__':unittest.main()
