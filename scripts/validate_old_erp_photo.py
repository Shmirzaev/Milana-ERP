"""Validate original bytes and exact model identity captured from the old ERP DOM."""
import hashlib
import re
from plan_catalog_qolip_sync import norm


def validate(photo, data):
    source = photo['source']
    sid = str(source['id'])
    assert sid.isdigit()
    assert source['url'] == f'https://10.100.50.199:8443/uzerp/prepareSewModel.htm?id={sid}'
    assert source['dom_model_no'] == source['model_no']
    assert norm(source['model_no']) == photo['model_no']
    assert source['captured_at'] and source['acquisition'] == 'rendered_dom_data_image'
    assert source['reviewed'] is True
    assert re.fullmatch(r'old_erp_model_20260908_\d+_[a-f0-9]{16}\.(jpg|png)', photo['stored_name'])
    assert hashlib.sha256(data).hexdigest() == photo['sha256'] == photo['original_sha256']
    assert len(data) == photo['stored_bytes'] == photo['original_bytes'] == source['bytes']
    assert photo['width'] > 256 and photo['height'] > 256
    assert photo['width'] * photo['height'] <= 50_000_000
    assert source['dom_dimensions'] == [photo['width'], photo['height']]


def validate_blank_target(code, general, expected_family, preview):
    assert norm((general or {}).get('model_no') or code) == expected_family, 'Model family changed'
    assert not preview, 'Old ERP fallback must only fill an empty model picture'


def validate_existing(photo, data):
    source = photo['source']
    assert source['id'] > 0 and source['reviewed'] is True
    assert source['url'] == f"https://erp.milanapremium.uz/models/{source['id']}"
    assert re.fullmatch(r'old_erp_model_[a-f0-9]{24}\.jpg', photo['stored_name'])
    assert source['file_url'] == '/storage/model-files/' + photo['stored_name']
    assert norm(source['printed_model_no']) == photo['model_no']
    assert hashlib.sha256(data).hexdigest() == photo['sha256'] == photo['original_sha256']
    assert len(data) == photo['stored_bytes'] == photo['original_bytes']
