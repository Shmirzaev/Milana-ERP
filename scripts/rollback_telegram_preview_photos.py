"""Undo only this task's verified preview-sized image insertions."""
import argparse
import hashlib
import json
from pathlib import Path
from sqlalchemy import text
from app.db.session import SessionLocal
from app.models import Model, ModelImage, User
from app.services.audit import log_action
from apply_telegram_model_photos import image_rows, protected_fingerprint


def run(path, checksum, apply=False):
    raw=Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==checksum
    manifest=json.loads(raw)
    targets={m['id']:m for p in manifest['photos'] for m in p['models']}
    urls={'/storage/model-files/'+p['stored_name'] for p in manifest['photos']}
    inserted={r['model_id']:r for r in manifest['inserted'] if r['model_id'] in targets and r['file_url'] in urls}
    assert len(inserted)==len(targets)
    with SessionLocal() as db:
        assert db.execute(text('select current_database()')).scalar()=='erp'
        db.execute(text('select pg_advisory_xact_lock(20260905,56843)'))
        models={m.id:m for m in db.query(Model).filter(Model.id.in_(targets)).order_by(Model.id).with_for_update().all()}
        before=image_rows(db); protected=protected_fingerprint(db)
        current={r['id']:r for r in before}
        for mid,target in targets.items():
            assert models[mid].code==target['code']
            new=inserted[mid]
            assert current[new['id']]==new
            expected=[]
            for old in target['before_images']:
                row=dict(old)
                if row['image_type']=='model': row['is_primary']=False
                expected.append(row)
            expected.append(new)
            assert [r for r in before if r['model_id']==mid]==sorted(expected,key=lambda r:r['id'])
            for old in target['before_images']:
                if old['image_type']=='model':
                    db.get(ModelImage,old['id']).is_primary=old['is_primary']
            db.delete(db.get(ModelImage,new['id']))
        db.flush()
        assert protected_fingerprint(db)==protected
        after=image_rows(db)
        for mid,target in targets.items():
            assert [r for r in after if r['model_id']==mid]==target['before_images']
        result={'mode':'apply' if apply else 'dry_run','families_restored':len(manifest['photos']),
                'model_records_restored':len(targets),'protected_fingerprints':protected}
        if apply:
            audit=log_action(db,db.get(User,1),'telegram_preview_rollback_20260905','ModelImage',None,
                             old_value={'removed_task_insertions':list(inserted.values())},new_value=result)
            db.flush();result['audit_id']=audit.id;db.commit()
            assert image_rows(db)==after
            result['committed_readback']='passed'
        else: db.rollback()
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(run(a.manifest,a.sha256,a.apply)))
