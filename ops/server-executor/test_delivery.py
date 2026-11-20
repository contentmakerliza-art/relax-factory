import contextlib,hashlib,importlib.util,io,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('delivery',Path(__file__).with_name('deliver-preview.py'))
delivery=importlib.util.module_from_spec(spec);spec.loader.exec_module(delivery)


class DeliveryTests(unittest.TestCase):
    def check(self,uncertain=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);delivery.SOURCE=root/'preview.mp4';delivery.SOURCE.write_bytes(b'preview-data'*2000)
            (root/'owner-review-ready.json').write_text(json.dumps({'ready_for_owner_review':True}))
            delivery.LEDGER=root/'delivery.json';delivery.LABEL='Quiet Pines Cabin test'
            job='codex-test-'+uuid.uuid4().hex
            manifest=Path('/tmp')/('codex-manifest-'+job+'.json');calls=[]
            def fake(path,method='GET',data=None):
                calls.append(path)
                if path=='/jobs/new':return {'id':job}
                if path.endswith('/telegram'):
                    self.assertTrue(manifest.exists())
                    self.assertEqual(json.loads(delivery.LEDGER.read_text())['stage'],'telegram_submission_uncertain')
                    if uncertain:raise TimeoutError('Response lost after request')
                return {}
            try:
                with patch.object(delivery,'call',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
                    delivery.main(register_only=True)
                    self.assertFalse(any(x.endswith('/telegram') for x in calls))
                    manifest.write_text(json.dumps(dict(job_id=job,recipe_verified=True,
                        preview_sha256=hashlib.sha256(delivery.SOURCE.read_bytes()).hexdigest())))
                    if uncertain:
                        with self.assertRaises(TimeoutError):delivery.main(send_only=True)
                    else:delivery.main(send_only=True)
                    delivery.main(send_only=True)
                self.assertEqual(len([x for x in calls if x.endswith('/telegram')]),1)
            finally:
                manifest.unlink(missing_ok=True)

    def test_register_prepare_then_send_exactly_once(self):self.check()
    def test_uncertain_send_is_never_repeated(self):self.check(uncertain=True)


if __name__=='__main__':unittest.main()
