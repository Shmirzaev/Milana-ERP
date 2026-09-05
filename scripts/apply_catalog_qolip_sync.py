"""Guarded, atomic application of an explicitly reviewed catalog data manifest."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelSize, ModelColor, User
from app.services.audit import log_action

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def image_fingerprint(db):
    return digest([list(r) for r in db.execute(text("SELECT id,model_id,file_url,file_name,content_type,image_type,is_primary,md5(file_data) FROM model_images ORDER BY id"))])

def run(path, expected_hash, apply=False):
    raw=Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected_hash, 'Manifest hash mismatch'
    plan=json.loads(raw)
    url=urlparse(settings.DATABASE_URL.replace('postgresql+psycopg2://','postgresql://'))
    assert url.hostname=='172.16.10.3' and url.path=='/erp', 'Wrong database'
    with SessionLocal() as db:
        assert db.execute(text('select current_database()')).scalar()=='erp'
        assert db.execute(text('select version_num from alembic_version')).scalar()=='0113_variant_selling_price'
        db.execute(text("select pg_advisory_xact_lock(20260905, 33742)"))
        actor=db.get(User,1)
        assert actor is not None
        before_images=image_fingerprint(db)
        ids=[r['id'] for r in plan['qolip_updates']]
        existing={m.id:m for m in db.query(Model).filter(Model.id.in_(ids)).with_for_update().all()}
        assert len(existing)==len(ids)
        codes={m.code for m in db.query(Model.code)}
        created=[]
        for row in plan['qolip_updates']:
            m=existing[row['id']]
            assert m.code==row['code'] and m.catalog_scope=='standard' and not m.code.startswith('LEGACY-')
            details=copy.deepcopy(m.details_json or {})
            assert (details.get('general') or {})==row['before_general'], f'Concurrent model change: {m.code}'
            details.setdefault('general',{})['qolip_no']=row['qolip_no']
            details['general']['mold_no']=row['qolip_no']
            m.details_json=details
        for row in plan['creates']:
            assert row['code'] not in codes, f'Already present: {row["code"]}'
            assert row['model_no']!='00000000' and (row['model_no'],row['variant_no'])!=('XJ3062','V-5709')
            general={'model_no':row['model_no'],'variant_no':row['variant_no'],'name':row['name'],'product':row['source_product']}
            if row['qolip_no']:general.update(qolip_no=row['qolip_no'],mold_no=row['qolip_no'])
            details={'general':general,'old_erp_catalog_sync_20260905':{'source_master_ids':row['source_master_ids'],'source_variant_ids':row['source_variant_ids'],'source_master_names':row['source_master_names'],'source':'authenticated old ERP catalog capture 2026-09-05'}}
            m=Model(code=row['code'],name=row['name'],catalog_scope='standard',status='draft',created_by=actor.id,sam_minutes=0,details_json=details)
            db.add(m);db.flush()
            for size in row['sizes']:db.add(ModelSize(model_id=m.id,size=size))
            for color in row['colors']:db.add(ModelColor(model_id=m.id,color_name=color))
            created.append({'id':m.id,'code':m.code})
        db.flush()
        assert before_images==image_fingerprint(db), 'Image data changed'
        result={'mode':'apply' if apply else 'dry_run','qolip_updates':len(ids),'created':created,'unchanged_image_fingerprint':before_images,'manifest_sha256':expected_hash}
        if apply:
            audit=log_action(db,actor,'sync_old_erp_catalog_qolip_20260905','model',None,old_value={'qolip_updates':plan['qolip_updates']},new_value=result)
            db.flush()
            result['audit_id']=audit.id
            db.commit()
            for row in plan['qolip_updates']:
                db.expire_all();m=db.get(Model,row['id']);g=m.details_json['general']
                assert g['qolip_no']==row['qolip_no'] and g['mold_no']==row['qolip_no']
            assert before_images==image_fingerprint(db)
            result['committed_readback']='passed'
        else:db.rollback()
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    print(json.dumps(run(args.manifest,args.sha256,args.apply),ensure_ascii=False))
