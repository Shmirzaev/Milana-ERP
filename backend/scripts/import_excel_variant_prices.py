"""Plan exact variant price updates and apply a reviewed, fingerprinted plan.

Input is extracted workbook data, never executable workbook content. The caller
must validate a fresh production database backup before calling apply_plan.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re


PRICE_FIELDS = (
    'selling_price', 'selling_price_currency', 'selling_price_source',
    'selling_price_request_id', 'selling_price_updated_at',
)
CONFUSABLES = str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H',
                           'О':'O','Р':'P','С':'C','Т':'T','Х':'X','У':'Y'})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     default=str).encode()).hexdigest()


def norm(value):
    return re.sub(r'[\s_-]+', '', str(value or '').upper().translate(CONFUSABLES))


def identity(code):
    match = re.fullmatch(r'(.+?)[-\s]*[VВ][-\s]*(\d+)', str(code).strip(), re.I)
    if not match:
        match = re.fullmatch(r'([A-ZА-Я]{2,3}[-\s]*\d+)[-\s]+(\d+)', str(code).strip(), re.I)
    return (norm(match[1]), norm(match[2])) if match else None


def model_identity(model):
    general = model.get('general') or {}
    model_no = general.get('model_no') or general.get('modelNo')
    variant = general.get('variant_no') or general.get('variantNo')
    if model_no and variant:
        variant = re.sub(r'^[VВ][-\s]*', '', str(variant), flags=re.I)
        return norm(model_no), norm(variant)
    return identity(model['code'])


def make_plan(source, snapshot, *, include_legacy=False):
    source_groups = defaultdict(list)
    exclusions = []
    blank = 0
    for row in source['rows']:
        if row['amount'] is None or str(row['amount']).strip() == '':
            blank += 1
            continue
        key = identity(row['code'])
        if not key and include_legacy:
            key = ('legacy', norm(row['code']))
        if not key:
            exclusions.append({**row, 'reason':'no_explicit_variant'})
            continue
        price = Decimal(str(row['amount']).replace(',', '.'))
        if not price.is_finite() or price < 0:
            raise ValueError('Invalid price')
        source_groups[key].append({**row, 'target':str(price + Decimal('0.30'))})
    index = defaultdict(list)
    for model in snapshot['models']:
        if model['catalog_scope'] == 'standard':
            key = model_identity(model)
            if not key and include_legacy:
                key = ('legacy', norm(model['code']))
            if key:
                index[key].append(model)
    changes, unchanged, matches, conflicts, duplicates = [], [], [], [], []
    for key, rows in sorted(source_groups.items()):
        if len({Decimal(row['target']) for row in rows}) != 1:
            conflicts.append({'identity':list(key), 'rows':rows})
            continue
        if len(rows) > 1:
            duplicates.append({'identity':list(key), 'rows':rows})
        candidates = index.get(key, [])
        if not candidates:
            exclusions.extend({**row, 'reason':'no_exact_erp_variant'} for row in rows)
            continue
        for model in candidates:
            if model['selling_price_currency'] not in (None, 'USD'):
                raise ValueError('Currency mismatch')
            entry = {'id':model['id'], 'code':model['code'], 'identity':list(key),
                     'source_rows':[row['row'] for row in rows], 'source_code':rows[0]['code'],
                     'excel_price':rows[0]['amount'], 'target':rows[0]['target'],
                     'before':{k:model[k] for k in PRICE_FIELDS},
                     'identity_hash':digest({k:model[k] for k in ('code','catalog_scope','factory_code','general')})}
            matches.append(entry)
            previous = model['selling_price']
            if previous is not None and Decimal(previous) == Decimal(entry['target']) and model['selling_price_currency'] == 'USD':
                unchanged.append(entry)
            else:
                changes.append(entry)
    summary = {'source_rows':len(source['rows']), 'blank_prices':blank,
               'priced_rows':len(source['rows'])-blank, 'matched_variants':len(matches),
               'changes':len(changes), 'already_correct':len(unchanged),
               'excluded_rows':len(exclusions), 'conflicting_identities':len(conflicts),
               'identical_duplicate_identities':len(duplicates)}
    plan = {'source_sha256':source['sha256'], 'source_name':source['name'],
            'include_legacy':include_legacy,
            'increment':'0.30', 'currency':'USD', 'revision':snapshot['revision'],
            'summary':summary, 'changes':changes, 'unchanged':unchanged,
            'exclusions':exclusions, 'conflicts':conflicts, 'duplicates':duplicates}
    plan['sha256'] = digest(plan)
    return plan


def apply_plan(db, plan, confirmed_hash):
    from sqlalchemy import text
    from app.models import Model
    from app.services.audit import log_action

    if plan['sha256'] != confirmed_hash or digest({k:v for k,v in plan.items() if k != 'sha256'}) != confirmed_hash:
        raise ValueError('Plan fingerprint mismatch')
    if db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != plan['revision']:
        raise ValueError('Database revision changed')
    db.execute(text("SET LOCAL lock_timeout = '10s'"))
    models = db.query(Model).filter(Model.id.in_([row['id'] for row in plan['changes']])).order_by(Model.id).with_for_update().all()
    if len(models) != len(plan['changes']):
        raise ValueError('Target variant missing')
    expected = {row['id']:row for row in plan['changes']}
    for model in models:
        row = expected[model.id]
        general = (model.details_json or {}).get('general')
        current_identity = {'code':model.code, 'catalog_scope':model.catalog_scope,
                            'factory_code':model.factory_code, 'general':general}
        if digest(current_identity) != row['identity_hash']:
            raise ValueError('Variant identity changed since review')
        for field in PRICE_FIELDS:
            value = getattr(model, field)
            actual = str(value) if value is not None else None
            prior = row['before'][field]
            if actual != (str(prior) if prior is not None else None):
                raise ValueError(f'Price changed since review: {model.code}')
        if Decimal(row['target']) != Decimal(str(row['excel_price']).replace(',','.')) + Decimal('0.30'):
            raise ValueError('Incorrect increment')
    changed_at = datetime.now(timezone.utc)
    for model in models:
        model.selling_price = Decimal(expected[model.id]['target'])
        model.selling_price_currency = 'USD'
        model.selling_price_source = 'excel'
        model.selling_price_request_id = None
        model.selling_price_updated_at = changed_at
    audit = None
    if models:
        audit = log_action(db, None, 'import_excel_variant_prices', 'ModelSellingPriceExcelImport',
                          old_value={'variants':[{'id':r['id'], 'code':r['code'], **r['before']} for r in plan['changes']]},
                          new_value={'plan_sha256':confirmed_hash, 'source_sha256':plan['source_sha256'],
                                     'source_name':plan['source_name'], 'increment':'0.30', 'currency':'USD',
                                     'reason':'User-requested Excel amount plus 0.30',
                                     'variants':[{'id':r['id'], 'code':r['code'], 'price':r['target'], 'source_rows':r['source_rows']} for r in plan['changes']]})
    db.flush()
    return {'changed':len(models), 'audit_id':audit.id if audit else None,
            'plan_sha256':confirmed_hash, 'changed_at':str(changed_at)}
