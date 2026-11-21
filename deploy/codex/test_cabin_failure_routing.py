import unittest,json,tempfile,hashlib
from pathlib import Path
from cabin_failure_routing import action,evidence_key,record_verified_rebuild
class FailureRoutingTests(unittest.TestCase):
 def test_proven_rebuild_requires_same_raw_bytes_and_exact_reviewed_preview(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);parent='cabin06-fullframe-v9-20261121';fixed=parent.replace('-fullframe-','-fixed-')
   before=root/'assets'/parent;after=root/'assets'/fixed;before.mkdir(parents=True);after.mkdir(parents=True)
   raw=root/'raw.mp4';raw.write_bytes(b'unchanged raw animation')
   sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
   (before/'preview.mp4').write_bytes(b'bad assembly');(after/'preview.mp4').write_bytes(b'good assembly')
   (before/'pipeline.json').write_text(json.dumps({'stage':'rejected_preview','defects':['ghosting']}))
   (after/'recipe-and-checks.json').write_text(json.dumps({'publication_loop_mode':'repeat','local_masks':False,'source_sha256':sha(raw)}))
   (after/'final-preview-qc.json').write_text(json.dumps({'verdict':'READY_FOR_OWNER_PREVIEW','defects':[],'preview_sha256':sha(after/'preview.mp4')}))
   receipt={'stage':'sent_for_owner_approval','request_id':fixed,'job_id':'owner-test'}
   result=record_verified_rebuild(root,parent,fixed,receipt,raw)
   self.assertEqual(result['route'],'ASSEMBLY_REPAIR');self.assertEqual(result['source_defects'],[])
   raw.write_bytes(b'other generation')
   with self.assertRaises(ValueError):record_verified_rebuild(root,parent,fixed,receipt,raw)
 def test_final_defect_alone_never_authorizes_generation(self):
  self.assertEqual(action('rejected_preview'),'needs_comparison')
  for route in ['UNCERTAIN','unknown',None]:self.assertEqual(action('rejected_preview',{'route':route}),'needs_review')
 def test_proven_source_defect_and_proven_assembly_defect_take_different_paths(self):
  self.assertEqual(action('rejected_preview',{'route':'SOURCE_REGENERATE'}),'source_retry')
  self.assertEqual(action('rejected_preview',{'route':'ASSEMBLY_REPAIR'}),'assembly_repair')
  self.assertEqual(action('rejected'),'source_retry')
 def test_comparison_cache_is_bound_to_both_media_and_defects(self):
  key=evidence_key('source','preview',['ghosting'])
  self.assertEqual(key,evidence_key('source','preview',['ghosting']))
  for args in [('changed','preview',['ghosting']),('source','new',['ghosting']),('source','preview',['cat moves'])]:self.assertNotEqual(key,evidence_key(*args))
if __name__=='__main__':unittest.main()
