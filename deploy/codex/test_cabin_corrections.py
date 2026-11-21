import json,tempfile,unittest
from pathlib import Path
import cabin_corrections as c
class CorrectionTests(unittest.TestCase):
 def test_real_blurred_trail_report_gets_geometry_fix(self):
  p=c.plan('Base',[{'request_id':'old','defects':['На спинке кресла виден размытый серо-голубой след, который тянется вниз к ковру.']}],'video')
  self.assertEqual(p['categories'],['geometry']);self.assertFalse(p['requires_review'])
 def test_long_base_and_multiple_defects_fit_actual_runway_limit(self):
  defects=['Нет заметного снегопада','Снег внутри комнаты','Кот шевелит головой','Деформация кладки','Камера движется','Яркое отражение в топке']
  p=c.plan('Original detailed scene. '*40,[{'request_id':'old','defects':defects}],'video')
  self.assertLessEqual(len(p['prompt']),1000);self.assertIn('Locked tripod',p['prompt'])
  self.assertIn('Dense, abundant snowfall',p['prompt']);self.assertTrue(p['prompt'].endswith('.'))
 def test_real_particle_report_and_word_kotoroe_are_not_cat_motion(self):
  text='Внутри комнаты видны светлые размытые частицы поверх кресла, которое перекрывает окно, и на деревянном потолке.'
  p=c.plan('Base',[{'request_id':'old','defects':[text]}],'video')
  self.assertEqual(p['categories'],['indoor_snow']);self.assertFalse(p['requires_review'])
 def test_indoor_snow_gets_specific_positive_instruction(self):
  evidence=[{'request_id':'old','defects':['Снежинки видны внутри комнаты на фоне потолочных балок и обивки кресла.']}]
  p=c.plan('Base prompt',evidence,'video')
  self.assertEqual(p['categories'],['indoor_snow']);self.assertIn('room air stays completely clear',p['prompt']);self.assertFalse(p['requires_review'])
 def test_missing_snow_is_not_misclassified_as_indoor(self):
  p=c.plan('Base',[{'request_id':'old','defects':['На 20 фрагментах окна падающие снежинки не различимы.']}],'video')
  self.assertEqual(p['categories'],['outdoor_snow']);self.assertIn('abundant snowfall',p['prompt'])
 def test_cat_motion_and_geometry_have_distinct_fixes(self):
  p=c.plan('Base',[{'request_id':'old','defects':['Кот поворачивает голову и уши.','Двоение контуров кладки и мебели.']}],'video')
  self.assertEqual(p['categories'],['cat_motion','geometry']);self.assertIn('exact same head angle',p['prompt']);self.assertIn('sharply aligned',p['prompt'])
 def test_assembly_audio_and_unknown_defects_do_not_buy_generations(self):
  for defect in ['Скачок на склейке петли','Звук слишком громкий','Необычная ошибка ABC']:
   with self.subTest(defect=defect):self.assertTrue(c.plan('Base',[{'request_id':'old','defects':[defect]}],'video')['requires_review'])
 def test_only_rejected_exact_prior_ids_supply_feedback(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for rid,stage in [('old','rejected_preview'),('good','held_for_motion_and_audio_review'),('unrelated','rejected')]:
    p=root/'assets'/rid/'pipeline.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'stage':stage,'defects':['snow indoors']}))
   self.assertEqual(c.feedback(root,['old','good']),[])
   (root/'assets/old/failure-stage-comparison.json').write_text(json.dumps({'route':'SOURCE_REGENERATE','source_defects':['snow indoors']}))
   self.assertEqual([x['request_id'] for x in c.feedback(root,['old','good'])],['old'])
 def test_restart_keeps_frozen_request_even_if_feedback_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'request.json';proposed={'request_id':'next','source':'/downloads/source.jpg','prompt':'Base','model':'Gen-4 Turbo'}
   evidence=[{'request_id':'old','defects':['Нет заметного снегопада']}]
   first=c.prepare(path,proposed,evidence,'video',root/'audit');raw=path.read_bytes()
   again=c.prepare(path,proposed,[],'video',root/'audit')
   self.assertEqual(first,again);self.assertEqual(path.read_bytes(),raw);self.assertEqual(len(list((root/'audit').glob('*'))),1)
 def test_previously_reserved_video_is_not_rewritten(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'request.json';r={'request_id':'next','source':'source','prompt':'Already reserved','model':'Gen-4 Turbo'};path.write_text(json.dumps(r))
   out=c.prepare(path,dict(r,prompt='Base'),[],'video',root/'audit')
   self.assertTrue(out['reserved_request_retained']);self.assertEqual(json.loads(path.read_text()),r)
 def test_new_image_gets_static_correction_and_preserves_schema(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'image.json';r={'request_id':'image','source':'source','prompt':'Base'};path.write_text(json.dumps(r))
   out=c.prepare(path,r,[{'request_id':'old','defects':['Кот шевелит головой']}],'image',root/'audit')
   actual=json.loads(path.read_text());self.assertEqual(set(actual),set(r));self.assertIn('compact stable pose',actual['prompt']);self.assertFalse(out['requires_review'])
if __name__=='__main__':unittest.main()
