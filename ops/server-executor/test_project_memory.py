import json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import project_memory as memory


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.patches=[patch.object(memory,'ROOT',root/'executor'),patch.object(memory,'DATA',root/'data'),patch.object(memory,'MEMORY',root/'executor/project-memory')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        memory.MEMORY.mkdir(parents=True);memory.DATA.mkdir()
        shutil.copy2(Path(__file__).parent/'project-memory/policy.json',memory.MEMORY/'policy.json')

    def row(self,job='20261120-193143-4575',label='Little Paris Jazz Cafe — 32 Bologna',status='одобрено',time=100,comments=None):
        return dict(job_id=job,label=label,status=status,time=time,comments=comments or [],archived=False)

    def test_scope_and_exhale_exception(self):
        paris=memory.context('Little Paris Jazz Cafe')
        ids={r['id'] for r in paris['active_rules']}
        self.assertIn('paris_existing_snow',ids);self.assertNotIn('cabin_fullframe',ids)
        exhale=memory.context('Exhale to Sleep');ids={r['id'] for r in exhale['active_rules']}
        self.assertIn('exhale_no_snow',ids);self.assertNotIn('mountain_snow',ids)

    def test_owner_history_is_durable_and_refresh_does_not_repeat_it(self):
        original_policy=(memory.MEMORY/'policy.json').read_bytes()
        row=self.row();memory.refresh({row['job_id']:row});memory.refresh({row['job_id']:row})
        p=memory.MEMORY/'episodes'/(row['job_id']+'.json');self.assertEqual(len(json.loads(p.read_text())['history']),1)
        row.update(status='правка',time=101,comments=[{'text':'фон тише на 3 дБ'}])
        memory.refresh({row['job_id']:row});card=json.loads(p.read_text())
        self.assertEqual(len(card['history']),2)
        self.assertEqual(card['owner_decision']['status'],'правка')
        self.assertEqual((memory.MEMORY/'policy.json').read_bytes(),original_policy)

    def test_approval_does_not_invent_publication_or_verified_reference(self):
        row=self.row();memory.refresh({row['job_id']:row})
        card=json.loads((memory.MEMORY/'episodes'/(row['job_id']+'.json')).read_text())
        self.assertEqual(card['actual_publications'],[])
        self.assertEqual(json.loads((memory.MEMORY/'examples.json').read_text()),[])

    def test_verified_positive_reference_and_examples_are_channel_scoped(self):
        row=self.row();p=memory.ROOT/'publication-manifests';p.mkdir()
        (p/(row['job_id']+'.json')).write_text(json.dumps({'recipe_verified':True,'preview_sha256':'known'}))
        memory.refresh({row['job_id']:row})
        examples=memory.context('Little Paris Jazz Cafe',request='Bologna')['examples']
        self.assertEqual(examples[0]['kind'],'owner_approved_verified')
        self.assertEqual(memory.context('Quiet Pines Cabin')['examples'],[])

    def test_resolved_false_rejection_is_not_a_negative_training_example(self):
        folder=memory.ROOT/'assets/cabin22-fullframe-v15-20261120';(folder/'qa-history').mkdir(parents=True)
        (folder/'pipeline.json').write_text(json.dumps({'stage':'rejected_preview','defects':['не виден снег']}))
        (folder/'qa-history/pipeline-before-native-window-review.json').write_text('{}')
        (folder/'final-preview-qc.json').write_text(json.dumps({'verdict':'READY_FOR_OWNER_PREVIEW','defects':[]}))
        memory.refresh({});examples=memory.context('Quiet Pines Cabin',stage='preview_qc',request='снег')['examples']
        self.assertEqual(examples[0]['kind'],'resolved_check_error')
        self.assertFalse(any(e['kind']=='automatic_reject' for e in examples))

    def test_only_active_rules_change_quality_cache_key(self):
        first=memory.context('Quiet Pines Cabin',stage='preview_qc')['policy_fingerprint']
        config=memory.policy();config['proposed_not_active'].append({'text':'новая идея'})
        (memory.MEMORY/'policy.json').write_text(json.dumps(config))
        self.assertEqual(memory.context('Quiet Pines Cabin',stage='preview_qc')['policy_fingerprint'],first)
        config['channels']['quiet-pines']['rules'][0]['text']+=' Updated requirement.'
        (memory.MEMORY/'policy.json').write_text(json.dumps(config))
        self.assertNotEqual(memory.context('Quiet Pines Cabin',stage='preview_qc')['policy_fingerprint'],first)

    def test_bad_identity_and_unknown_channel_fail_closed(self):
        with self.assertRaises(ValueError):memory.context('Unknown project')
        with self.assertRaises(ValueError):memory.context('Quiet Pines Cabin',job_id='../secret')
        with self.assertRaises(ValueError):memory.context('Quiet Pines Cabin',request_id='../secret')

    def test_leniency_needs_three_new_distinct_size_only_rejections(self):
        memory.refresh({})
        state=json.loads((memory.MEMORY/'quality-adjustments.json').read_text());start=state['counting_since']
        events=[dict(id=f'new-{i}',channel='quiet-pines',kind='automatic_reject',
                     summary='Снежинки немного крупнее желаемого размера',time=start+i) for i in (1,2,3)]
        memory.update_conditional_quality(memory.policy(),events[:2])
        ids={r['id'] for r in memory.context('Quiet Pines Cabin',stage='preview_qc')['active_rules']}
        self.assertNotIn('owner_authorized_snow_size_leniency',ids)
        memory.update_conditional_quality(memory.policy(),[events[0]]*3)
        ids={r['id'] for r in memory.context('Quiet Pines Cabin',stage='preview_qc')['active_rules']}
        self.assertNotIn('owner_authorized_snow_size_leniency',ids)
        memory.update_conditional_quality(memory.policy(),events)
        ids={r['id'] for r in memory.context('Quiet Pines Cabin',stage='preview_qc')['active_rules']}
        self.assertIn('owner_authorized_snow_size_leniency',ids)

    def test_critical_snow_defect_and_success_break_size_streak(self):
        self.assertFalse(memory.size_only_rejection('Крупные снежинки внутри комнаты'))
        self.assertFalse(memory.size_only_rejection('Крупные хлопья повторяются на склейке'))
        self.assertFalse(memory.size_only_rejection('Крупные снежинки заслоняют пейзаж'))
        memory.refresh({});start=json.loads((memory.MEMORY/'quality-adjustments.json').read_text())['counting_since']
        events=[dict(id=f'new-{i}',channel='quiet-pines',kind='automatic_reject',summary='Крупные снежинки',time=start+i) for i in (1,2,4)]
        events.append(dict(id='success',channel='quiet-pines',kind='automatic_pass',summary='OK',time=start+3))
        memory.update_conditional_quality(memory.policy(),events)
        state=json.loads((memory.MEMORY/'quality-adjustments.json').read_text())
        self.assertEqual(state['channels']['quiet-pines']['size_preference'],'normal')
