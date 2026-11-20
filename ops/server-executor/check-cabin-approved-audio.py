"""Read-only comparison of four approved Cabin excerpts to complete fireplace 9."""
import importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('identity','/tmp/inspect-paris-backlog.py')
identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
JOBS=['20261119-203840-ac20','20261119-204114-a9a4','20261119-204154-d82e','20261119-205140-f946']
reference=identity.samples(Path('/tmp/cabin-full-fireplace-9.wav'))
for jid in JOBS:
    folder=Path('/data')/jid;meta=json.loads((folder/'job.json').read_text())
    print(json.dumps({'job_id':jid,'correlation':identity.correlation(reference,
        identity.samples(folder/meta['output']))}),flush=True)
