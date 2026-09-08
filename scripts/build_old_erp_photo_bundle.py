"""Build blank-only model photo additions from exact old ERP source records."""
import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from PIL import Image
from plan_catalog_qolip_sync import norm
from validate_old_erp_photo import validate


def build(evidence, name='old-erp-photo-bundle-20260908', safety_name='photo-safety-before-old-erp-20260908.json'):
    read = lambda name: json.loads((evidence / name).read_text('utf-8-sig'))
    acquired = read('old-erp-photo-acquisition-20260908.json')
    reviewed = {r['old_id']: r for r in read('old-erp-photo-decisions-20260908.json') if r['accepted']}
    safety = read(safety_name)
    live = {m['id']: m for m in safety['models']}
    images = defaultdict(list)
    for row in safety['images']:
        images[row['model_id']].append(row)
    candidates = defaultdict(list)
    for row in acquired:
        review = reviewed.get(row['old_id'])
        if row.get('filename') and review and review['sha256'] == row['sha256'] and row['dom']['rows'] == [row['model_no']]:
            candidates[norm(row['model_no'])].append(row)
    targets = defaultdict(list)
    with (evidence / 'models-still-missing-pictures-20260908.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            mid = int(row['erp_link'].rsplit('/', 1)[1])
            current = live[mid]
            if current['code'] != row['model_code'] or mid > 8034:
                continue
            if any(i['image_type'] == 'model' for i in images[mid]):
                continue
            base = norm(row['model_no'])
            if norm((current['general'] or {}).get('model_no') or current['code']) != base:
                continue
            if (current['general'] or {}).get('variant_no') and current['effective_variant_url'] and not current['independent_variant_url']:
                continue
            targets[base].append({'id': mid, 'code': current['code'], 'before_images': images[mid],
                                  'before_variant_url': current['effective_variant_url']})
    assert Path(name).name == name and Path(safety_name).name == safety_name
    destination = evidence / name
    assert not (destination / 'manifest.json').exists(), 'Preserve existing manifests; use a new bundle name'
    (destination / 'files').mkdir(parents=True, exist_ok=True)
    photos = []
    for base, models in targets.items():
        if base not in candidates:
            continue
        row = max(candidates[base], key=lambda r: (r['width'] * r['height'], int(r['old_id'])))
        path = evidence / 'old-erp-model-originals' / row['filename']
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == row['sha256']
        with Image.open(path) as image:
            assert image.size == (row['width'], row['height'])
            image.verify()
        ext = path.suffix.lower()
        name = f"old_erp_model_20260908_{row['old_id']}_{row['sha256'][:16]}{ext}"
        photo = {'model_no': base, 'models': models, 'stored_name': name, 'sha256': row['sha256'],
                 'original_sha256': row['sha256'], 'stored_bytes': len(data), 'original_bytes': len(data),
                 'width': row['width'], 'height': row['height'], 'content_type': 'image/png' if ext == '.png' else 'image/jpeg',
                 'source': {'id': row['old_id'], 'url': row['url'], 'name': row['filename'],
                            'model_no': row['model_no'], 'dom_model_no': row['dom']['rows'][0],
                            'dom_dimensions': [row['width'], row['height']], 'captured_at': row['captured_at'],
                            'bytes': row['bytes'], 'acquisition': 'rendered_dom_data_image', 'reviewed': True,
                            'review_basis': reviewed[row['old_id']]['reason']}}
        validate(photo, data)
        shutil.copyfile(path, destination / 'files' / name)
        photos.append(photo)
    manifest = {'source_kind': 'old_erp_model_original', 'photos': photos}
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (destination / 'manifest.json').write_bytes(raw)
    return {'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'families': len(photos),
            'models': sum(len(p['models']) for p in photos), 'codes': [m['code'] for p in photos for m in p['models']]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='old-erp-photo-bundle-20260908')
    parser.add_argument('--safety', default='photo-safety-before-old-erp-20260908.json')
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1] / 'evidence', args.name, args.safety), ensure_ascii=False))
