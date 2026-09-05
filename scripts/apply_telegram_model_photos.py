"""Guarded model-picture replacement; never write variant/material images."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import selectinload
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelBOM, ModelImage, User
from app.api.routes.catalog import _fabric_picture_url_for_model, _variant_picture_url_for_model
from app.services.audit import log_action
from app.services.image_storage import prebuild_webp_thumbnails
from app.services.model_images import model_preview_image_url


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode())


def image_rows(db):
    return [dict(r._mapping) for r in db.execute(text(
        'SELECT id,model_id,file_url,file_name,content_type,image_type,is_primary,md5(file_data) AS data_md5 FROM model_images ORDER BY id'
    ))]


def protected_fingerprint(db):
    result = {}
    for table in ('models', 'model_bom', 'model_sizes', 'model_colors'):
        result[table] = digest([list(r) for r in db.execute(text(
            f'SELECT id, md5(row_to_json({table})::text) FROM {table} ORDER BY id'
        ))])
    result['non_model_images'] = digest([list(r) for r in db.execute(text(
        "SELECT id,md5(row_to_json(model_images)::text) FROM model_images WHERE coalesce(image_type,'') <> 'model' ORDER BY id"
    ))])
    return result


def load_models(db, ids):
    return {m.id: m for m in db.query(Model).options(
        selectinload(Model.images), selectinload(Model.bom).selectinload(ModelBOM.item)
    ).filter(Model.id.in_(ids)).order_by(Model.id).all()}


def has_variant(model):
    return bool(str(((model.details_json or {}).get('general') or {}).get('variant_no') or '').strip())


def run(bundle, expected_hash, apply=False):
    root = Path(bundle).resolve()
    raw = (root/'manifest.json').read_bytes()
    assert sha(raw) == expected_hash, 'Manifest hash mismatch'
    manifest = json.loads(raw)
    url = urlparse(settings.DATABASE_URL.replace('postgresql+psycopg2://','postgresql://'))
    assert url.hostname == '172.16.10.3' and url.path == '/erp', 'Wrong database'
    storage = Path(settings.MODEL_FILES_DIR).resolve()
    if apply:
        storage.mkdir(parents=True, exist_ok=True)
    for photo in manifest['photos']:
        name = photo['stored_name']
        assert re.fullmatch(r'telegram_model_20260905_\d+_[a-f0-9]{16}\.(png|jpe?g|webp)', name)
        data = (root/'files'/name).read_bytes()
        assert sha(data) == photo['sha256'] and len(data) == photo['stored_bytes']
        target = storage/name
        if target.exists():
            assert sha(target.read_bytes()) == photo['sha256'], 'Storage name collision'
        elif apply:
            with target.open('xb') as output:
                output.write(data)
        if apply:
            prebuild_webp_thumbnails(data, thumbnail_root=storage/'_thumbs', source_file_name=name)
    targets = [m for p in manifest['photos'] for m in p['models']]
    ids = [m['id'] for m in targets]
    assert len(ids) == len(set(ids)), 'Duplicate target model'
    with SessionLocal() as db:
        assert db.execute(text('select current_database()')).scalar() == 'erp'
        assert db.execute(text('select version_num from alembic_version')).scalar() == '0113_variant_selling_price'
        db.execute(text('select pg_advisory_xact_lock(20260905, 56843)'))
        db.query(Model.id).filter(Model.id.in_(ids)).order_by(Model.id).with_for_update().all()
        before = image_rows(db)
        protected = protected_fingerprint(db)
        models = load_models(db, ids)
        assert len(models) == len(ids)
        existing_variant_urls = {mid: _variant_picture_url_for_model(m) for mid, m in models.items()}
        before_by_model = {}
        for image in before:
            before_by_model.setdefault(image['model_id'], []).append(image)
        already = []
        pending = []
        for photo in manifest['photos']:
            target_url = '/storage/model-files/' + photo['stored_name']
            for target in photo['models']:
                mid = target['id']
                model = models[mid]
                assert model.code == target['code'] and model.catalog_scope == 'standard' and not model.code.startswith('LEGACY-')
                current = before_by_model.get(mid, [])
                applied = [r for r in current if r['file_url'] == target_url and r['image_type'] == 'model' and r['is_primary']]
                if applied:
                    assert len(applied) == 1
                    already.append(mid)
                    continue
                assert current == target['before_images'], f'Concurrent image change: {model.code}'
                assert not has_variant(model) or _fabric_picture_url_for_model(model) or not existing_variant_urls[mid], f'Existing variant uses model-photo fallback: {model.code}'
                assert existing_variant_urls[mid] == target['before_variant_url'], 'Concurrent variant picture change'
                for image in model.images:
                    if image.image_type == 'model' and image.is_primary:
                        image.is_primary = False
                db.add(ModelImage(model_id=mid, file_url=target_url,
                    file_name=photo['source']['name'], content_type=photo['content_type'],
                    image_type='model', is_primary=True, file_data=None))
                pending.append({'model_id': mid, 'file_url': target_url, 'source_message': photo['source']['id']})
        db.flush()
        assert protected_fingerprint(db) == protected, 'Protected catalog or variant image data changed'
        db.expire_all()
        reread = load_models(db, ids)
        for photo in manifest['photos']:
            target_url = '/storage/model-files/' + photo['stored_name']
            for target in photo['models']:
                model = reread[target['id']]
                assert model_preview_image_url(model) == target_url
                old_variant = existing_variant_urls[model.id]
                if old_variant and has_variant(model):
                    assert _variant_picture_url_for_model(model) == old_variant, 'An existing variant picture changed'
        after = image_rows(db)
        after_by_id = {r['id']: r for r in after}
        pending_ids = {r['model_id'] for r in pending}
        for old in before:
            expected = dict(old)
            if old['model_id'] in pending_ids and old['image_type'] == 'model':
                expected['is_primary'] = False
            assert after_by_id[old['id']] == expected, 'Unexpected existing image mutation'
        before_ids = {r['id'] for r in before}
        target_ids = set(ids)
        result = {'mode': 'apply' if apply else 'dry_run', 'manifest_sha256': expected_hash,
                  'photos': len(manifest['photos']), 'models_updated': len(pending),
                  'already_applied': len(already), 'protected_fingerprints': protected,
                  'existing_variant_pictures_preserved': sum(bool(v) and has_variant(models[mid]) for mid, v in existing_variant_urls.items()),
                  'inserted': [r for r in after if r['id'] not in before_ids]}
        if apply and pending:
            audit = log_action(db, db.get(User,1), 'telegram_model_photos_20260905', 'ModelImage', None,
                               old_value={'images': [r for r in before if r['model_id'] in target_ids]}, new_value=result)
            db.flush()
            result['audit_id'] = audit.id
            db.commit()
            assert protected_fingerprint(db) == protected
            db.expire_all()
            committed = load_models(db, ids)
            for row in pending:
                assert model_preview_image_url(committed[row['model_id']]) == row['file_url']
            result['committed_readback'] = 'passed'
        else:
            db.rollback()
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.bundle, args.sha256, args.apply), ensure_ascii=False))
