"""Atomic source-backed creation of two catalog variants and eight held packs."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from app.db.session import SessionLocal
from app.models import Model, ModelColor, ModelImage, ModelSize
from app.services.audit import log_action
import import_completed_packs as packs

IDENTITIES = {('XJ3062','5709'), ('PJ1239','6184')}


def read_catalog(args, payload):
    root=args.input.parent
    path=root/'catalog.json'
    if packs.file_sha256(path) != payload['catalog_manifest_sha256']:
        raise ValueError('Catalog manifest hash changed')
    models=json.loads(path.read_text(encoding='utf-8'))['models']
    if {tuple(m['identity'].split('|')) for m in models} != IDENTITIES or len(models)!=2:
        raise ValueError('Unexpected catalog identities')
    for m in models:
        if m['details_json']['old_erp_migration']['identity'] != m['identity']:
            raise ValueError('Source identity mismatch')
        if not m['sizes'] or len(m['sizes'])!=len(set(m['sizes'])):
            raise ValueError('Missing/duplicate source sizes')
        for name,digest in {**m['source_files'],m['image_file']:m['image_sha256']}.items():
            if Path(name).name!=name or packs.file_sha256(root/name)!=digest:
                raise ValueError('Source evidence changed')
        ops=m['details_json']['paid_operations']
        for factory in ('milana','besttex','eco_cotton'):
            scoped=[o for o in ops if o['sewingFactory']==factory]
            if len(scoped)!=m['operation_count'] or sum(Decimal(o['rate']) for o in scoped)!=Decimal(m['rate_per_factory']):
                raise ValueError('Source operation count/rate mismatch')
    return models


def absent_models(db, catalog):
    for model in db.query(Model).all():
        if packs.model_identity(model) in IDENTITIES or model.code in {m['code'] for m in catalog}:
            raise ValueError('Target catalog identity already exists; inspect before retry')


def verify_catalog(db,catalog):
    result=[]
    for source in catalog:
        model=db.query(Model).filter(Model.code==source['code']).one()
        if model.details_json!=source['details_json'] or model.name!=source['name'] or model.status!='approved' or model.catalog_scope!='standard':
            raise ValueError('Catalog readback mismatch')
        if sorted(s.size for s in model.sizes)!=sorted(source['sizes']):
            raise ValueError('Size readback mismatch')
        if len(model.images)!=1 or not model.images[0].is_primary or model.images[0].image_type!='model':
            raise ValueError('Model picture readback mismatch')
        img=model.images[0]
        disk=Path('/app')/img.file_url.lstrip('/')
        if packs.file_sha256(disk)!=source['image_sha256']:
            raise ValueError('Stored image changed')
        if sorted(c.color_name for c in model.colors)!=([source['color']] if source['color'] else []):
            raise ValueError('Color readback mismatch')
        result.append(dict(id=model.id,code=model.code,sizes=len(model.sizes),operations=len(model.details_json['paid_operations']),image=img.file_url))
    return result


def run(args):
    payload,rows=packs.read_manifest(args.input,args.photo_root,args.expected_manifest_sha256)
    catalog=read_catalog(args,payload)
    if len(rows)!=8 or sum(r['quantity'] for r in rows)!=494:
        raise ValueError('Unexpected pack scope')
    blank=[r['qr_code'] for r in rows if r['weight_kg'] is None]
    if blank!=['uzerp_ii_21492_1'] or any(r['target_kind']!='catalog' for r in rows):
        raise ValueError('Blank-weight or catalog scope changed')
    with SessionLocal() as db:
        warehouse,actor=packs.assert_target_guard(db,args)
        if args.mode=='verify':
            models=verify_catalog(db,catalog)
            resolved,_=packs.resolve_all(db,rows,3)
            state=packs.readback(db,rows,resolved,actor.id)
            db.rollback()
            return dict(mode='verify',models=models,state=state)
        db.execute(text('select pg_advisory_xact_lock(202609225709)'))
        absent_models(db,catalog)
        packs.assert_zero_collisions(db,rows)
        existing=[r for r in rows if (packs.normalized_base(r['model_number']),packs.normalized_variant(r['article'])) not in IDENTITIES]
        packs.resolve_all(db,existing,1)
        if args.mode=='dry-run':
            db.rollback()
            return dict(mode='dry-run',models_to_create=2,packs_to_create=8,quantity=494,known_weight_kg=payload['expected_known_weight_kg'],blank_weight_qr=blank,collisions=0)
        if args.confirm!='APPLY-8-COMPLETED-PACKS-TO-PRODUCTION' or args.environment!='production':
            raise ValueError('Explicit production apply guard missing')
        for source in catalog:
            model=Model(code=source['code'],name=source['name'],catalog_scope='standard',
                        details_json=source['details_json'],status='approved',created_by=actor.id,
                        approved_by=actor.id,approved_at=datetime.now(timezone.utc),sam_minutes=0)
            db.add(model);db.flush()
            db.add_all(ModelSize(model_id=model.id,size=size) for size in source['sizes'])
            if source['color']:
                db.add(ModelColor(model_id=model.id,color_name=source['color']))
            image_name=f"old_erp_master_{source['image_sha256']}.jpg"
            destination=Path('/app/storage/model-files')/image_name
            destination.parent.mkdir(parents=True,exist_ok=True)
            content=(args.input.parent/source['image_file']).read_bytes()
            if destination.exists():
                if packs.file_sha256(destination)!=source['image_sha256']:
                    raise ValueError('Existing file collision')
            else:
                with destination.open('xb') as stream:
                    stream.write(content)
            db.add(ModelImage(model_id=model.id,file_url='/storage/model-files/'+image_name,
                              file_name=source['image_file'],content_type='image/jpeg',
                              file_data=content,image_type='model',is_primary=True))
        db.flush()
        models=verify_catalog(db,catalog)
        audit=log_action(db,actor,'old_erp_catalog_import','Model',None,
                         new_value=dict(models=models,catalog_manifest_sha256=payload['catalog_manifest_sha256'],source='old ERP authenticated catalog'))
        db.flush()
        model_audit_id=audit.id
        resolved,_=packs.resolve_all(db,rows,3)
        pack_audit_id=packs.import_rows(db,rows,resolved,warehouse,actor,args.expected_manifest_sha256)
        state=packs.readback(db,rows,resolved,actor.id)
        db.commit()
    with SessionLocal() as db:
        packs.assert_target_guard(db,args)
        models=verify_catalog(db,catalog)
        resolved,_=packs.resolve_all(db,rows,3)
        state=packs.readback(db,rows,resolved,args.imported_by)
        db.rollback()
    return dict(mode='apply',committed=True,models=models,state=state,model_audit_id=model_audit_id,pack_audit_id=pack_audit_id)


if __name__=='__main__':
    print(json.dumps(run(packs.parse_args()),ensure_ascii=False,indent=2))
