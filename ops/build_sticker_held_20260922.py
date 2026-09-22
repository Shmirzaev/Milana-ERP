"""Build the explicitly authorized two-catalog/eight-pack follow-up."""
import hashlib
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'sticker-held-20260922'
FIRST = ROOT / 'outputs' / 'sticker-20260922'
sys.path.insert(0, str(ROOT / 'backend'))
from scripts.correct_old_erp_models_local import canonical_paid_operation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def master_model(base, variant, parent, expected_operations):
    master_path = OUT / f'master-{parent}.json'
    variant_path = OUT / f'variant-{variant}.json'
    source = json.loads(master_path.read_text(encoding='utf-8'))
    v = json.loads(variant_path.read_text(encoding='utf-8'))
    assert next(f['value'] for f in v['fields'] if f['name'] == 'sew-model') == str(parent)
    assert any(f['value'] == f'V-{variant}' for f in v['fields'])
    general_table = next(t for t in source['tables'] if t and t[0][0] == 'Дата')
    general = {r[0]: r[1] for r in general_table if len(r) > 1}
    assert general['Код Модели'] == base
    sizes_table = next(t for t in source['tables'] if t and t[0] == ['№', 'Размер Варианта Швейной Модели'])
    sizes = [r[1] for r in sizes_table if r[0].isdigit()]
    operations_table = next(t for t in source['tables'] if t and len(t[0]) == 8 and t[0][1] == 'Операции')
    raw_ops = []
    direction_map = {'Шв. Брак.':'sewMarriage', 'Шв. Переделка.':'sewCorrected', 'Шв. Сорт.':'sewGrade'}
    for r in operations_table:
        if not r[0].isdigit():
            continue
        raw_ops.append(dict(source_order=int(r[0]), name=r[1], duration=r[2], price=r[3].replace(' ', ''),
                            currency=r[4], stage=r[5],
                            control_change_direction=','.join(direction_map[x.strip()] for x in r[6].split(',') if x.strip()),
                            final_operation=r[7] == 'true'))
    assert len(raw_ops) == expected_operations
    paid = []
    for raw in raw_ops:
        op = canonical_paid_operation(raw)
        for factory in ('milana', 'besttex', 'eco_cotton'):
            paid.append(dict(op, id=op['id']+'--'+factory, sewingFactory=factory, legacySourceId=op['id']))
    recipe_table = next(t for t in source['tables'] if t and t[0] == ['№', 'Продукт', 'Кол-во', 'Вид Расхода'])
    recipes = [r for r in recipe_table if r[0].isdigit()]
    picture = OUT / f'master-{parent}.jpg'
    color = 'Rotatsion Baski' if variant == 6184 else None
    details = dict(general=dict(model_no=base, variant_no=str(variant), qolip_no=general['Имя'],
                                mold_no=general['Имя'], legacy_source_date=general['Дата'],
                                legacy_product=general['Продукт'], legacy_color=color or ''),
                   paid_operations=paid,
                   old_erp_migration=dict(identity=f'{base}|{variant}', source_key='old-erp-sticker-held-20260922',
                                          master_id=parent, variant_id=variant,
                                          master_url=source['url'], variant_url=v['url'],
                                          master_sha256=sha(master_path), variant_sha256=sha(variant_path),
                                          general=general, operations=raw_ops, recipes=recipes,
                                          source_variant_fields=v['fields']))
    return dict(identity=f'{base}|{variant}', code=f'{base}-{variant}', name=general['Продукт'],
                details_json=details, sizes=sizes, color=color, image_file=picture.name,
                image_sha256=sha(picture), source_files={master_path.name:sha(master_path),variant_path.name:sha(variant_path)},
                operation_count=len(raw_ops), rate_per_factory=str(sum(Decimal(r['price']) for r in raw_ops)))


def main():
    models = [master_model('XJ3062',5709,1803,45),master_model('PJ1239',6184,3286,40)]
    catalog = dict(models=models)
    (OUT/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    held = json.loads((FIRST/'held.json').read_text(encoding='utf-8'))
    source = json.loads((FIRST/'extracted.json').read_text(encoding='utf-8'))
    assert len(held) == 8 and sum(r['quantity'] for r in held) == 494
    rows=[]
    for raw in held:
        row={k:raw.get(k,'') for k in ('qr_code','model_number','article','quantity','weight_kg','sizes','color','product','fabric','client')}
        row.update(target_kind='catalog', allowed_blank_weight=raw['weight_kg'] is None,
                   source_workbook='sticker.zip', source_workbook_sha256=source['source_zip_sha256'],
                   source_reference=f"{raw['source_file']}, page {raw['source_page']}, label {raw['source_sequence']}",
                   source_photo=raw['source_file'],source_photo_sha256=raw['file_sha256'],review_status='approved',
                   review_basis='User explicitly requested source catalog import and all held packs; absent PM7007 weight must remain blank.')
        rows.append(row)
    manifest=dict(version=2,expected_rows=8,expected_quantity=494,
                  expected_known_weight_kg=str(sum((Decimal(r['weight_kg']) for r in rows if r['weight_kg']),Decimal(0))),
                  expected_null_weight_rows=1,expected_unique_identities=3,catalog_manifest_sha256=sha(OUT/'catalog.json'),rows=rows)
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with zipfile.ZipFile(OUT/'bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in ('manifest.json','catalog.json','master-1803.json','master-3286.json','variant-5709.json','variant-6184.json','master-1803.jpg','master-3286.jpg'):
            z.write(OUT/name,name)
        for name in ('import_completed_packs.py','import_sticker_held_20260922.py'):
            z.write(ROOT/'ops'/name,name)
        for name in sorted({r['source_photo'] for r in rows}):
            z.write(FIRST/'pdfs'/name,'photos/'+name)
    print(json.dumps({k:v for k,v in manifest.items() if k!='rows'}))
    print(json.dumps([{'identity':m['identity'],'sizes':m['sizes'],'operations':m['operation_count'],'rate_per_factory':m['rate_per_factory']} for m in models]))


if __name__ == '__main__':
    main()
