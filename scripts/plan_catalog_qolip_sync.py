"""Build a source-evidenced catalog delta; never guess ambiguous identities."""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANS = str.maketrans('АВСЕНКМОРТХУІЈ', 'ABCEHKMOPTXYIJ')

def norm(value):
    return ''.join(c for c in str(value or '').upper().translate(TRANS) if c.isalnum())

def variant(value):
    value = re.sub(r'^V[\s_-]*', '', str(value or '').upper())
    return str(int(value)) if value.isdigit() else norm(value)

def identity(row):
    g = row.get('general_details') or {}
    base, v = g.get('model_no'), g.get('variant_no')
    if not base:
        match = re.fullmatch(r'([A-ZА-ЯІЈ]{1,3})-?(\d+)(?:-(?:V-?)?(\d+))?', row['code'].upper())
        if match:
            base, v = match[1] + match[2], v or match[3]
    return norm(base), variant(v)

def valid_master(row):
    return bool(re.fullmatch(r'[A-ZА-ЯІЈ]{1,3}-?\d+V?',row['model_no'].upper()))

def numeric_qolip(value):
    return bool(re.fullmatch(r'\d[\d /.,+\-]*', value.strip()))

def build(masters, variants, production):
    by_base, old_by_identity, new_by_identity = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in masters:
        if valid_master(row): by_base[norm(row['model_no'])].append(row)
    for row in variants: old_by_identity[norm(row['model_no']),variant(row['variant_no'])].append(row)
    for row in production:
        if row['catalog_scope']=='standard' and not row['code'].startswith('LEGACY-'):
            new_by_identity[identity(row)].append(row)
    held, updates, creates = [], [], []
    def source_for(base, oldrows):
        candidates=by_base.get(base,[])
        refs={r['sewing_model_ref'] for r in oldrows}
        linked=[r for r in candidates if r['qolip_no'] in refs]
        return linked if any(numeric_qolip(r['qolip_no']) for r in linked) else candidates
    def qolip(sources):
        vals={r['qolip_no'] for r in sources if numeric_qolip(r['qolip_no'])}
        return next(iter(vals)) if len(vals)==1 else None
    for key, rows in new_by_identity.items():
        sources=source_for(key[0],old_by_identity.get(key,[]))
        q=qolip(sources)
        if not q:
            if sources and len({r['qolip_no'] for r in sources if numeric_qolip(r['qolip_no'])})>1:
                held.append({'kind':'ambiguous_qolip','identity':key,'sources':sources})
            continue
        for row in rows:
            g=row.get('general_details') or {}
            if g.get('qolip_no')==q and g.get('mold_no')==q:continue
            updates.append({'id':row['id'],'code':row['code'],'before_general':g,'qolip_no':q,'source_master_ids':[s['old_id'] for s in sources if s['qolip_no']==q]})
    for key, rows in old_by_identity.items():
        if key in new_by_identity:continue
        if key==('XJ3062','5709') or not re.fullmatch(r'[A-Z]{1,3}\d+',key[0]) or not key[1].isdigit():
            held.append({'kind':'excluded_or_invalid_variant','identity':key,'source_ids':[r['old_id'] for r in rows]});continue
        other_bases=[other for other in new_by_identity if other[1]==key[1] and other[0]!=key[0]]
        if other_bases:
            held.append({'kind':'variant_number_other_model','identity':key,'existing_identities':other_bases});continue
        sources=source_for(key[0],rows)
        names={r['product'] for r in sources if r['product']}
        if len(names)>1 or not sources:
            held.append({'kind':'ambiguous_variant_master','identity':key,'sources':sources});continue
        creates.append({'code':key[0]+'-'+key[1],'model_no':key[0],'variant_no':'V-'+key[1], 'name':next(iter(names)) if names else key[0], 'qolip_no':qolip(sources),'source_master_ids':[r['old_id'] for r in sources], 'source_variant_ids':[r['old_id'] for r in rows],'colors':sorted({r['color'] for r in rows if r['color']})})
    represented={key[0] for key in new_by_identity}|{r['model_no'] for r in creates}
    for base,sources in by_base.items():
        if base in represented:continue
        names={r['product'] for r in sources if r['product']}
        if len(names)>1:
            held.append({'kind':'ambiguous_standalone_master','model_no':base,'sources':sources});continue
        creates.append({'code':base,'model_no':base,'variant_no':'','name':next(iter(names)) if names else base,'qolip_no':qolip(sources),'source_master_ids':[r['old_id'] for r in sources],'source_variant_ids':[],'colors':[]})
    return {'qolip_updates':updates,'creates':creates,'held':held}

if __name__=='__main__':
    load=lambda name:json.loads((ROOT/'evidence'/name).read_text(encoding='utf8'))
    plan=build(load('old-models.json')['rows'],load('old-variants.json')['rows'],load('production-before.json')['models'])
    (ROOT/'evidence'/'catalog-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:len(v) for k,v in plan.items()}))
