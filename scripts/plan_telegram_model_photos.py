"""Match labeled Telegram attachments to exact, existing model families."""
import json
import re
from collections import defaultdict
from pathlib import Path

from plan_catalog_qolip_sync import TRANS, identity, norm

MODEL_TOKEN = re.compile(r"(?<![A-Z0-9])([A-Z]{1,3}[ _-]*\d{3,6}(?:V(?![ _-]*\d))?)(?!\d)")
IMAGE_EXTENSION = re.compile(r"\.(?:png|jpe?g|webp)$", re.I)


def build(files, models, downloaded=None):
    downloaded = {row['model_no']: row['source']['id'] for row in (downloaded or [])}
    families = defaultdict(list)
    for model in models:
        if model['catalog_scope'] == 'standard' and not model['code'].startswith('LEGACY-'):
            base, _ = identity(model)
            if re.fullmatch(r'[A-Z]{1,3}\d+V?', base) and not re.fullmatch(r'V\d+', base):
                families[base].append(model)
    candidates = defaultdict(list)
    for attachment in files:
        name = attachment.get('name') or ''
        if not IMAGE_EXTENSION.search(name):
            continue
        tokens = {norm(token) for token in MODEL_TOKEN.findall(name.upper().translate(TRANS))
                  if not re.fullmatch(r'V\d+', norm(token))}
        matched = tokens & families.keys()
        # Multi-model family portraits are usable, but a single-model image
        # is preferred. Camera and generic generated filenames are not evidence.
        for base in matched:
            candidates[base].append({**attachment, 'labeled_models': sorted(tokens)})
    selected = []
    for base, choices in sorted(candidates.items()):
        source = max(choices, key=lambda r: (
            downloaded.get(base) == r['id'],
            len(r['labeled_models']) == 1,
            bool(re.search(r'\.jpe?g$', r['name'], re.I)),
            int(r['id'].removeprefix('shared-mediamessage-')),
        ))
        selected.append({
            'model_no': base,
            'source': source,
            'models': [{'id': m['id'], 'code': m['code'], 'before_images': m['images']}
                       for m in families[base]],
        })
    return {
        'source_group': 'Milana Fotosessiya',
        'source_group_id': '-1002871659105',
        'indexed_files': len(files),
        'selected': selected,
        'unmatched_families': sorted(families.keys() - candidates.keys()),
    }


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / 'evidence'
    downloaded_path = root/'telegram-downloads.json'
    catalog_path = root/'production-final-catalog.json'
    if not catalog_path.exists():
        catalog_path = root/'production-after-catalog.json'
    plan = build(json.loads((root/'telegram-shared-files.json').read_text('utf-8')),
                 json.loads(catalog_path.read_text('utf-8'))['models'],
                 json.loads(downloaded_path.read_text('utf-8')) if downloaded_path.exists() else [])
    (root/'telegram-photo-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'families': len(plan['selected']),
                      'model_records': sum(len(r['models']) for r in plan['selected']),
                      'unmatched': len(plan['unmatched_families'])}))
