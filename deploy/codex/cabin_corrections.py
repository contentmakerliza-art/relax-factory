"""Bounded, evidence-based prompt corrections; no model calls or submissions."""
import hashlib
import json
import re
from pathlib import Path

VERSION = '2026-11-21-dense-visible-snow-v3'
REJECTED = {'rejected', 'rejected_motion', 'rejected_preview'}


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def feedback(root, prior_ids):
    found = []
    for rid in prior_ids:
        folder = root / 'assets' / rid
        pipeline = read(folder / 'pipeline.json')
        if pipeline.get('stage') not in REJECTED:
            continue
        defects = pipeline.get('defects', [])
        if pipeline.get('stage')=='rejected_preview':
            comparison=read(folder/'failure-stage-comparison.json')
            if comparison.get('route')!='SOURCE_REGENERATE':continue
            defects=comparison.get('source_defects',[])
        if not defects:
            for name in ('final-preview-qc.json', 'visual-qc.json'):
                qc = read(folder / name)
                if qc.get('verdict') == 'REJECT':
                    defects = qc.get('defects', [])
                    if defects:
                        break
        if defects:
            found.append({'request_id': rid, 'defects': [str(x)[:1200] for x in defects[:6]]})
    return found[-3:]


def classify(text):
    t = text.lower()
    kinds = set()
    if re.search(r'сне[гж]|snow|flake', t) or (
            re.search(r'частиц|пятн|particle|speck', t) and
            re.search(r'внутри|помещен|потол|крес|интерьер|indoors|ceiling|upholstery', t)):
        if re.search(r'внутри|помещен|потол|обивк|поверх.*крес|indoors|inside|ceiling', t):
            kinds.add('indoor_snow')
        else:
            kinds.add('outdoor_snow')
    if re.search(r'\bкот(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|кошк|голов|уш[иае]|лап|хвост|\bcat\b|head|ear|paw|tail', t):
        kinds.add('cat_motion')
    if re.search(r'камер|наезд|зум|camera|zoom', t):
        kinds.add('camera')
    if re.search(r'деформа|двоени|контур|геометр|мебел|кладк|размыт.{0,70}след|blurred streak|morph|geometry|ghost|furniture', t):
        kinds.add('geometry')
    if re.search(r'отраж|зеркал|reflection|mirror', t):
        kinds.add('reflections')
    if re.search(r'плам|огн|топк|полен|камин|flame|firebox|hearth|logs', t):
        kinds.add('fireplace')
    if re.search(r'склей|стык|петл|seam|loop|crossfade', t):
        kinds.add('assembly')
    if re.search(r'звук|аудио|audio|sound', t):
        kinds.add('audio')
    return kinds


VIDEO = {
    'outdoor_snow': 'Dense, abundant snowfall is immediately obvious across the entire outdoor view for the full shot. Hundreds of small distinct flakes drift diagonally in gentle changing wind behind closed window glass; the mountain or forest view stays readable.',
    'indoor_snow': 'Snowfall stays in the distant exterior behind closed window glass. The room air stays completely clear; chairs, upholstery and ceiling beams stay dry and sharply visible in front of the windows.',
    'cat_motion': 'The sleeping cat keeps the exact same head angle, relaxed ears, paws and tail throughout. Its chin rests on its paws. Only the flank breathes imperceptibly slowly.',
    'camera': 'A rigid locked tripod holds one identical composition and perspective for the entire shot.',
    'geometry': 'The window frames, stonework, furniture edges and books remain rigid and sharply aligned throughout; the original scene geometry stays unchanged.',
    'reflections': 'Glass reflections stay faint and physically plausible. The fireplace interior remains matte dark brick with a clear view of its existing wood fire.',
    'fireplace': 'Animate the flames of the existing fireplace while preserving the shape and position of its firebox, logs and stonework. The small flames move naturally inside the original opening.',
}
IMAGE = {
    'outdoor_snow': 'Show dense, abundant exterior snowfall: many small distinct flakes across the entire outdoor view, immediately visible against distant trees, with the landscape readable through closed windows.',
    'indoor_snow': 'Keep the indoor air, ceiling, chairs and upholstery clear and dry; all falling snow belongs to the exterior behind closed window glass.',
    'cat_motion': 'Keep the cat naturally curled asleep with its chin supported on its paws and relaxed ears, in a compact stable pose suitable for nearly still animation.',
    'camera': 'Preserve the original fixed camera framing and perspective.',
    'geometry': 'Preserve coherent rigid geometry and clear single edges of the existing windows, furniture and masonry.',
    'reflections': 'Use minimal plausible glass reflections and a matte dark fireplace interior.',
    'fireplace': 'Preserve the shape of the existing fireplace, its firebox, logs and stonework, with a small natural wood fire inside the original opening.',
}

COMPACT_VIDEO_BASE = (
    'Locked tripod, fixed composition throughout. The curled sleeping cat keeps its head, '
    'ears, paws and tail still, with barely perceptible flank breathing. Animate the existing '
    'wood flames within the unchanged firebox and logs. Furniture and masonry remain rigid. '
    'Dense abundant snowfall with many small flakes stays outdoors behind closed windows. Clear dry indoor air; '
    'minimal plausible reflections and natural firelight.'
)


def plan(base_prompt, evidence, kind):
    rules = VIDEO if kind == 'video' else IMAGE
    kinds = set()
    unknown = []
    for item in evidence:
        for defect in item['defects']:
            matched = classify(defect)
            kinds.update(matched)
            if not matched:
                unknown.append(defect)
    # Editing a generation prompt cannot fix an audio or assembly-only defect.
    hold = bool(unknown) or bool(kinds & {'assembly', 'audio'})
    focused = [k for k in rules if k in kinds]
    # Required on the first attempt too; keep defect categories evidence-based.
    if 'outdoor_snow' not in focused:focused.insert(0,'outdoor_snow')
    corrections = [rules[k] for k in focused]
    prompt = ' '.join(corrections + [base_prompt]) if corrections else base_prompt
    applied = list(focused)
    if kind == 'video' and len(prompt) > 1000:
        # Retain whole instructions and Cabin invariants, not a cut-off sentence.
        prompt = COMPACT_VIDEO_BASE
        applied = []
        selected = []
        for category in focused:
            candidate = ' '.join(selected + [rules[category], COMPACT_VIDEO_BASE])
            if len(candidate) <= 1000:
                selected.append(rules[category]);applied.append(category)
                prompt = candidate
    if kind == 'video' and not 1 <= len(prompt) <= 1000:
        raise ValueError('Corrected Runway prompt exceeds provider limit')
    return {'version': VERSION, 'kind': kind, 'categories': sorted(kinds),
            'applied_focused_categories': applied,
            'evidence': evidence, 'unknown_defects': unknown, 'requires_review': hold,
            'base_prompt_sha256': hashlib.sha256(base_prompt.encode()).hexdigest(),
            'prompt': prompt}


def prepare(request_path, proposed, evidence, kind, audit_folder):
    """Freeze one exact request and audit before submission; resume it unchanged."""
    audit_folder.mkdir(parents=True, exist_ok=True)
    audit = audit_folder / (proposed['request_id'] + '-correction.json')
    if audit.exists():
        saved = read(audit)
        if saved.get('requires_review'):
            if saved.get('version') != VERSION and not plan(proposed['prompt'], evidence, kind)['requires_review']:
                history=audit_folder/'history';history.mkdir(exist_ok=True)
                # Only an unsent held request reaches prepare(); generation ledgers
                # are checked by the caller before invoking this function.
                archive=history/(audit.name+'.'+saved.get('version','unversioned'))
                audit.rename(archive)
                return prepare(request_path,proposed,evidence,kind,audit_folder)
            return saved
        actual = read(request_path)
        if actual != saved['request']:
            raise ValueError('Frozen correction request differs; inspect instead of resubmitting')
        return saved
    correction = plan(proposed['prompt'], evidence, kind)
    if correction['requires_review']:
        with audit.open('x') as f:
            json.dump(correction, f, ensure_ascii=False, indent=2)
        return correction
    if request_path.exists() and kind == 'video':
        # An earlier process may have reserved this video request before its ledger.
        actual = read(request_path)
        if any(actual.get(k) != v for k, v in proposed.items() if k != 'prompt'):
            raise ValueError('Reserved request provenance differs')
        correction['reserved_request_retained'] = True
        correction['request'] = actual
    else:
        actual = dict(proposed, prompt=correction['prompt'])
        correction['request'] = actual
        temp = request_path.with_suffix('.correction.tmp')
        temp.write_text(json.dumps(actual, ensure_ascii=False, indent=2))
        temp.replace(request_path)
    correction['actual_prompt_sha256'] = hashlib.sha256(correction['request']['prompt'].encode()).hexdigest()
    with audit.open('x') as f:
        json.dump(correction, f, ensure_ascii=False, indent=2)
    return correction
