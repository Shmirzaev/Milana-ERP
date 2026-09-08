"""Explicit schema and source exclusions for reviewed catalog repair manifests."""


def validate_revision(manifest, actual):
    expected = manifest.get('database_revision', '0113_variant_selling_price')
    assert expected in ('0113_variant_selling_price', '0114_warehouse_stocktake'), 'Unreviewed schema'
    assert actual == expected, 'Database revision differs from reviewed manifest'


def validate_photo_source(photo, source_kind):
    source = photo['source']
    if source_kind == 'old_erp_model_original':
        assert not (photo['model_no'] == 'XJ3001' and str(source['id']) in ('1269', '1204')), 'User rejected conflicting X-3001/4 label'
    elif source_kind == 'telegram_original':
        assert source['id'] not in ('shared-mediamessage-4916', 'shared-mediamessage-10201'), 'Known conflicting printed model label'
