"""A preview-only rejection cannot authorize another provider generation."""
import hashlib,json


def evidence_key(source, preview, defects):
    return hashlib.sha256(json.dumps([source,preview,defects],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def action(stage, comparison=None):
    if stage=='rejected':return 'source_retry'
    if stage=='rejected_motion':return 'needs_comparison'
    if stage!='rejected_preview':return 'not_rejected'
    if comparison is None:return 'needs_comparison'
    route=comparison.get('route')
    if route=='SOURCE_REGENERATE':return 'source_retry'
    if route=='ASSEMBLY_REPAIR':return 'assembly_repair'
    return 'needs_review'


def record_verified_rebuild(root, parent, repaired, receipt, source):
    """A passing reconstruction from identical raw bytes proves assembly causation."""
    if repaired!=parent.replace('-fullframe-','-fixed-'):raise ValueError('Repair parent differs')
    if receipt.get('stage')!='sent_for_owner_approval' or receipt.get('request_id')!=repaired:
        raise ValueError('Verified new preview receipt required')
    before=root/'assets'/parent;after=root/'assets'/repaired
    recipe=json.loads((after/'recipe-and-checks.json').read_text())
    qc=json.loads((after/'final-preview-qc.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest()!=recipe['source_sha256']:
        raise ValueError('Repair used a different raw source')
    if qc.get('verdict')!='READY_FOR_OWNER_PREVIEW' or qc.get('defects'):
        raise ValueError('Rebuilt preview has not passed visual review')
    if recipe.get('publication_loop_mode')!='repeat' or recipe.get('local_masks') is not False:
        raise ValueError('Whole-frame loop repair evidence required')
    pipeline=json.loads((before/'pipeline.json').read_text())
    preview_hash=hashlib.sha256((before/'preview.mp4').read_bytes()).hexdigest()
    new_hash=hashlib.sha256((after/'preview.mp4').read_bytes()).hexdigest()
    if qc.get('preview_sha256')!=new_hash:raise ValueError('Reviewed rebuilt bytes changed')
    value={'route':'ASSEMBLY_REPAIR','state':'completed','source_defects':[],
           'origin':'verified_rebuild_from_identical_source','repaired_request_id':repaired,
           'repaired_preview_sha256':new_hash,'job_id':receipt['job_id'],
           'evidence_key':evidence_key(recipe['source_sha256'],preview_hash,pipeline.get('defects',[])),
           'evidence':'The same raw source passed after full-frame normalization and cyclic assembly, without a new generation.'}
    target=before/'failure-stage-comparison.json'
    if target.exists():
        old=json.loads(target.read_text())
        if old==value:return value
        history=before/'qa-history';history.mkdir(exist_ok=True)
        import time
        (history/('stage-comparison-before-proven-rebuild-'+str(time.time_ns())+'.json')).write_text(json.dumps(old,ensure_ascii=False,indent=2))
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(target)
    return value
