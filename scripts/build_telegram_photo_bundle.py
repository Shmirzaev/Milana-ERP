"""Build an exact, reviewable photo manifest from verified source evidence."""
import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path


def build(plan, prepared, safety, partial=False):
    prepared = {r['model_no']: r for r in prepared}
    models = {r['id']: r for r in safety['models']}
    images = defaultdict(list)
    for row in safety['images']:
        images[row['model_id']].append(row)
    photos, held, missing = [], [], []
    for family in plan['selected']:
        targets = []
        for target in family['models']:
            model = models[target['id']]
            assert model['code'] == target['code']
            has_variant = bool(str((model.get('general') or {}).get('variant_no') or '').strip())
            if has_variant and model['effective_variant_url'] and not model['independent_variant_url']:
                held.append({'model_no': family['model_no'], 'id': model['id'], 'code': model['code'],
                             'reason': 'Existing variant picture uses model-picture fallback'})
                continue
            targets.append({'id': model['id'], 'code': model['code'],
                            'before_images': images[model['id']],
                            'before_variant_url': model['effective_variant_url']})
        if not targets:
            continue
        photo = prepared.get(family['model_no'])
        if not photo:
            missing.append(family['model_no'])
            continue
        assert photo['source']['id'] == family['source']['id'], 'Prepared source differs from selected source'
        assert photo['source']['name'] == family['source']['name']
        photos.append({key: photo[key] for key in ('model_no', 'source', 'stored_name', 'stored_bytes',
                      'sha256', 'original_sha256', 'pixel_sha256', 'width', 'height', 'content_type')} |
                      {'models': targets, 'original_bytes': photo['bytes']})
    assert partial or not missing, f'{len(missing)} model families still require photos'
    return {'source_group': plan['source_group'], 'source_group_id': plan['source_group_id'],
            'indexed_files': plan['indexed_files'], 'photos': photos, 'held': held,
            'missing_downloads': missing, 'unmatched_families': plan['unmatched_families']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parents[1]/'evidence'
    read = lambda name: json.loads((evidence/name).read_text('utf-8'))
    manifest = build(read('telegram-photo-plan.json'), read('telegram-prepared.json'),
                     read('photo-safety-final-before.json'), args.partial)
    destination = evidence/('telegram-photo-bundle-partial' if args.partial else 'telegram-photo-bundle')
    (destination/'files').mkdir(parents=True, exist_ok=True)
    for photo in manifest['photos']:
        source = evidence/'telegram-prepared'/photo['stored_name']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == photo['sha256']
        target = destination/'files'/photo['stored_name']
        if not target.exists():
            shutil.copyfile(source, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == photo['sha256']
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (destination/'manifest.json').write_bytes(raw)
    print(json.dumps({'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'photos': len(manifest['photos']),
                      'model_records': sum(len(r['models']) for r in manifest['photos']),
                      'held': len(manifest['held']), 'missing_downloads': len(manifest['missing_downloads'])}))
