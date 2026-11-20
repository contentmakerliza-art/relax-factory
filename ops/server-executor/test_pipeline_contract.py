"""A prepared version must be accepted by every subsequent delivery stage."""
import ast,re,unittest
from pathlib import Path


class PipelineContractTest(unittest.TestCase):
    def test_all_stages_accept_full_prepared_version_range(self):
        base=Path(__file__).parent
        for name in ['production-retry.py','pipeline-one.py','follow-generation.py',
                     'try-long-segment.py','retry-download.py','final-preview-review.py','deliver-preview.py']:
            tree=ast.parse((base/name).read_text())
            patterns=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call)
                      and isinstance(n.func,ast.Attribute) and n.func.attr=='fullmatch'
                      and n.args and isinstance(n.args[0],ast.Constant)
                      and isinstance(n.args[0].value,str) and 'fullframe' in n.args[0].value]
            self.assertTrue(patterns,name)
            for version in (1,12,15,18):
                rid=f'cabin22-fullframe-v{version}-20261120'
                self.assertTrue(any(re.fullmatch(p,rid) for p in patterns),(name,rid))
            for rid in ['../cabin22-fullframe-v15-20261120','cabin22-fullframe-v19-20261120']:
                self.assertFalse(any(re.fullmatch(p,rid) for p in patterns),(name,rid))
