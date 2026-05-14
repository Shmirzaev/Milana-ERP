"""Seed initial data: departments, roles, admin user, sample catalog, sample orders."""
from datetime import datetime, timedelta, timezone
import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models  # noqa
from app.models import (
    Role, Department, User, Customer, Supplier, Warehouse, Item,
    Brand, Collection, Model, ModelSize, ModelColor, ModelBOM,
    CollectionModel, SalesOrder, SalesOrderItem, StockBatch, SewingFlow,
)


DEPARTMENTS = [
    ("Sales", "SLS"), ("Planning", "PLN"), ("Fabric & Accessories Storage", "STR"),
    ("Cutting", "CUT"), ("Printing", "PRT"), ("Sewing", "SEW"),
    ("Packaging", "PKG"), ("Ready Product Storage", "FGS"),
    ("Finance", "FIN"), ("Modeling / PLM", "MOD"), ("HR", "HR"),
    ("Waste Department", "WST"), ("Management / Admin", "ADM"),
]

# Permissions per role (using "*" for full access)
ROLES = {
    "Admin": ["*"],
    "Management": [
        "management.view", "management.approve", "finance.view", "admin.audit",
        "tasks.manage", "processes.view", "sewing.flows",
        "production.override_deadline",
        # Management can also act on behalf of the floor in emergencies
        # (e.g. recording output after a deadline override). They don't
        # normally do this, but the permission unblocks the path.
        "cutting.records", "printing.records", "sewing.records", "packaging.records",
        "cutting.bundles", "printing.bundles", "sewing.bundles", "packaging.packages",
    ],
    "Sales": ["sales.orders", "sales.customers", "processes.view"],
    "Planning": [
        "planning.requirements", "planning.production", "planning.view",
        "processes.view", "sewing.flows",
    ],
    "Modeling": ["modeling.models", "modeling.bom", "modeling.brands", "modeling.collections", "modeling.approve"],
    "Storage": ["storage.receive", "storage.transfer", "storage.items", "storage.suppliers", "storage.packages", "storage.shipment"],
    "Cutting": ["cutting.records", "cutting.bundles"],
    "Printing": ["printing.records", "printing.bundles"],
    "Sewing": ["sewing.records", "sewing.bundles"],
    "Packaging": ["packaging.records", "packaging.packages"],
    "ReadyStorage": ["storage.packages", "storage.shipment"],
    "Waste": ["waste.receive", "waste.sell", "waste.disposal"],
    "Finance": ["finance.view", "finance.invoice", "finance.payment"],
    "HR": ["hr.employees"],
}


SEWING_FLOWS = [
    # 30 production lines. Naming: Line 01 .. Line 30
    (f"Line {i:02d}", f"SEW-{i:02d}") for i in range(1, 31)
]

LEGACY_MODELS_CSV = Path(__file__).resolve().parents[2] / "data" / "legacy_models.csv"


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _infer_season(name: str) -> str | None:
    lower = name.lower()
    if "bahor" in lower or "yoz" in lower:
        return "Spring/Summer"
    if "kuz" in lower or "qish" in lower:
        return "Autumn/Winter"
    return None


def _import_legacy_models(db: Session, admin: User) -> tuple[int, int, int]:
    """Import historical model rows from CSV snapshot if file is present."""
    if not LEGACY_MODELS_CSV.exists():
        return (0, 0, 0)

    legacy_brand = db.query(Brand).filter(Brand.name == "Legacy Catalog").first()
    if not legacy_brand:
        legacy_brand = Brand(name="Legacy Catalog", description="Imported historical model catalog")
        db.add(legacy_brand)
        db.flush()

    existing_models = db.query(Model.id, Model.code).all()
    model_code_map = {code.strip().lower(): mid for (mid, code) in existing_models if code}
    existing_sizes = {(model_id, size) for (model_id, size) in db.query(ModelSize.model_id, ModelSize.size).all() if size}
    collection_rows = db.query(Collection.id, Collection.name).filter(Collection.brand_id == legacy_brand.id).all()
    collection_map = {name.strip().lower(): cid for (cid, name) in collection_rows if name}
    collection_links = {(cid, mid) for (cid, mid) in db.query(CollectionModel.collection_id, CollectionModel.model_id).all()}

    created_models = 0
    created_sizes = 0
    created_collections = 0
    now_utc = datetime.now(timezone.utc)

    with LEGACY_MODELS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 7:
                continue

            legacy_code, model_code, category, product_name, size_name, unit, collection_name = [_clean_text(v) for v in row[:7]]
            if not model_code or not product_name:
                continue

            code_norm = model_code.lower()
            model_id = model_code_map.get(code_norm)
            if model_id is None:
                description = f"Legacy code: {legacy_code}"
                if unit:
                    description += f"; Unit: {unit}"
                model = Model(
                    code=model_code,
                    name=product_name,
                    category=category or None,
                    description=description,
                    status="approved",
                    created_by=admin.id,
                    approved_by=admin.id,
                    approved_at=now_utc,
                    sam_minutes=0,
                )
                db.add(model)
                db.flush()
                model_id = model.id
                model_code_map[code_norm] = model_id
                created_models += 1

            if size_name and (model_id, size_name) not in existing_sizes:
                db.add(ModelSize(model_id=model_id, size=size_name))
                existing_sizes.add((model_id, size_name))
                created_sizes += 1

            if collection_name:
                coll_key = collection_name.lower()
                coll_id = collection_map.get(coll_key)
                if coll_id is None:
                    c = Collection(
                        brand_id=legacy_brand.id,
                        name=collection_name,
                        season=_infer_season(collection_name),
                        status="approved",
                    )
                    db.add(c)
                    db.flush()
                    coll_id = c.id
                    collection_map[coll_key] = coll_id
                    created_collections += 1

                link_key = (coll_id, model_id)
                if link_key not in collection_links:
                    db.add(CollectionModel(collection_id=coll_id, model_id=model_id))
                    collection_links.add(link_key)

    return (created_models, created_sizes, created_collections)


def seed():
    Base.metadata.create_all(bind=engine)
    # Apply column-level patches to existing tables (Render free tier has no
    # Shell, so we can't run ALTER TABLE by hand).
    try:
        from app.db import schema_hotfix
        schema_hotfix.run(engine)
    except Exception as e:
        print(f"seed: schema_hotfix skipped — {e}")
    db: Session = SessionLocal()
    try:
        # ----- Departments -----
        dept_map = {}
        for name, code in DEPARTMENTS:
            d = db.query(Department).filter(Department.code == code).first()
            if not d:
                d = Department(name=name, code=code)
                db.add(d); db.flush()
            dept_map[code] = d

        # ----- Roles -----
        # Insert missing roles AND refresh permissions on existing ones so new
        # permissions added in code propagate to running databases.
        role_map = {}
        for name, perms in ROLES.items():
            r = db.query(Role).filter(Role.name == name).first()
            if not r:
                r = Role(name=name, permissions=perms)
                db.add(r); db.flush()
            else:
                if set(r.permissions or []) != set(perms):
                    r.permissions = perms
            role_map[name] = r

        # ----- Admin user -----
        admin = db.query(User).filter(User.email == "admin@example.com").first()
        if not admin:
            admin = User(
                name="System Admin",
                email="admin@example.com",
                password_hash=hash_password("admin12345"),
                role_id=role_map["Admin"].id,
                department_id=dept_map["ADM"].id,
                is_active=True,
            )
            db.add(admin); db.flush()

        # A user per role (for quick demos)
        role_user_specs = [
            ("Sales", "sales@example.com", "SLS"),
            ("Planning", "planning@example.com", "PLN"),
            ("Modeling", "modeling@example.com", "MOD"),
            ("Storage", "storage@example.com", "STR"),
            ("Cutting", "cutting@example.com", "CUT"),
            ("Printing", "printing@example.com", "PRT"),
            ("Sewing", "sewing@example.com", "SEW"),
            ("Packaging", "packaging@example.com", "PKG"),
            ("ReadyStorage", "fgs@example.com", "FGS"),
            ("Waste", "waste@example.com", "WST"),
            ("Finance", "finance@example.com", "FIN"),
            ("HR", "hr@example.com", "HR"),
            ("Management", "mgr@example.com", "ADM"),
        ]
        for role_name, email, dcode in role_user_specs:
            if not db.query(User).filter(User.email == email).first():
                db.add(User(
                    name=role_name + " User", email=email,
                    password_hash=hash_password("demo12345"),
                    role_id=role_map[role_name].id,
                    department_id=dept_map[dcode].id, is_active=True,
                ))

        # ----- Customers / Suppliers -----
        if not db.query(Customer).first():
            db.add_all([
                Customer(name="ACME Apparel Co.", phone="+1-555-0100", email="orders@acme.example", address="123 Market St"),
                Customer(name="Global Fashion Ltd.", phone="+1-555-0200", email="po@global.example", address="89 Trade Blvd"),
            ])
        if not db.query(Supplier).first():
            db.add_all([
                Supplier(name="TexFab Mills", phone="+1-555-1100", email="sales@texfab.example"),
                Supplier(name="Accessory World", phone="+1-555-1200", email="info@aworld.example"),
            ])

        # ----- Warehouses (one per relevant department) -----
        wh_specs = [
            ("Fabric Storage", "fabric_storage", "STR"),
            ("Accessory Storage", "accessory_storage", "STR"),
            ("Packaging Storage", "packaging", "PKG"),
            ("Cutting Floor", "cutting", "CUT"),
            ("Printing Floor", "printing", "PRT"),
            ("Sewing Floor", "sewing", "SEW"),
            ("Finished Goods", "finished_goods", "FGS"),
            ("Waste Yard", "waste", "WST"),
        ]
        wh_map = {}
        for name, type_, dcode in wh_specs:
            w = db.query(Warehouse).filter(Warehouse.name == name).first()
            if not w:
                w = Warehouse(name=name, type=type_, department_id=dept_map[dcode].id)
                db.add(w); db.flush()
            wh_map[type_] = w

        # ----- Items -----
        items_specs = [
            ("FAB-COT-001", "Cotton Jersey 180gsm", "fabric", "meter", 3.50, True),
            ("FAB-POL-001", "Polyester Blend 220gsm", "fabric", "meter", 4.20, True),
            ("ACC-BTN-001", "Plastic Button 12mm", "accessory", "pcs", 0.05, False),
            ("ACC-ZIP-001", "Metal Zipper 20cm", "accessory", "pcs", 0.35, False),
            ("ACC-THR-001", "Polyester Thread Black", "accessory", "roll", 1.20, False),
            ("PKG-BAG-001", "Polybag 30x40cm", "packaging", "pcs", 0.04, False),
            ("WST-FAB-001", "Fabric Cutting Waste", "waste", "kg", 0.10, False),
        ]
        item_map = {}
        for sku, name, cat, unit, cost, track in items_specs:
            it = db.query(Item).filter(Item.sku == sku).first()
            if not it:
                it = Item(sku=sku, name=name, category=cat, unit=unit, default_cost=cost, track_batch=track)
                db.add(it); db.flush()
            item_map[sku] = it

        # ----- Stock batches -----
        if not db.query(StockBatch).first():
            db.add(StockBatch(
                item_id=item_map["FAB-COT-001"].id, batch_no="B-COT-202401",
                color="white", width=160, gsm=180, quantity=500, unit="meter",
                cost_per_unit=3.50, warehouse_id=wh_map["fabric_storage"].id, qc_status="passed",
            ))
            db.add(StockBatch(
                item_id=item_map["FAB-POL-001"].id, batch_no="B-POL-202401",
                color="black", width=150, gsm=220, quantity=300, unit="meter",
                cost_per_unit=4.20, warehouse_id=wh_map["fabric_storage"].id, qc_status="passed",
            ))

        # ----- Brand / Collection / Model -----
        brand = db.query(Brand).filter(Brand.name == "Urban Co.").first()
        if not brand:
            brand = Brand(name="Urban Co.", description="Casual urban wear")
            db.add(brand); db.flush()
        coll = db.query(Collection).filter(Collection.name == "SS-2025").first()
        if not coll:
            coll = Collection(brand_id=brand.id, name="SS-2025", season="Spring/Summer", year=2025, status="approved")
            db.add(coll); db.flush()

        model = db.query(Model).filter(Model.code == "T-SHIRT-001").first()
        if not model:
            model = Model(
                code="T-SHIRT-001", name="Classic Crew Neck T-Shirt",
                category="t-shirt", description="180gsm cotton crew neck.",
                status="approved", created_by=admin.id, approved_by=admin.id,
                approved_at=datetime.now(timezone.utc),
            )
            db.add(model); db.flush()
            for s in ["S", "M", "L", "XL"]:
                db.add(ModelSize(model_id=model.id, size=s))
            for c, code in [("white", "#FFFFFF"), ("black", "#000000")]:
                db.add(ModelColor(model_id=model.id, color_name=c, color_code=code))
            db.add(ModelBOM(model_id=model.id, item_id=item_map["FAB-COT-001"].id,
                            quantity_per_piece=1.4, unit="meter", waste_percent=8.0))
            db.add(ModelBOM(model_id=model.id, item_id=item_map["ACC-THR-001"].id,
                            quantity_per_piece=0.02, unit="roll", waste_percent=5.0))
            db.add(ModelBOM(model_id=model.id, item_id=item_map["PKG-BAG-001"].id,
                            quantity_per_piece=1, unit="pcs", waste_percent=0.0))

        # ----- 30 Sewing Flows -----
        for name, code in SEWING_FLOWS:
            if not db.query(SewingFlow).filter(SewingFlow.code == code).first():
                db.add(SewingFlow(
                    name=name, code=code,
                    description=f"Sewing flow {name}",
                    capacity_per_day=200,
                    is_active=True,
                ))

        # ----- Sample Sales Order -----
        if not db.query(SalesOrder).first():
            customer = db.query(Customer).first()
            so = SalesOrder(
                order_no="SO-2025-000001", customer_id=customer.id,
                order_type="client_order", status="confirmed",
                deadline=datetime.now(timezone.utc) + timedelta(days=30),
                total_amount=0, notes="Sample seeded order.", created_by=admin.id,
            )
            db.add(so); db.flush()
            total = 0.0
            for size, qty, price in [("S", 50, 12.0), ("M", 75, 12.0), ("L", 75, 12.0), ("XL", 50, 12.0)]:
                db.add(SalesOrderItem(
                    sales_order_id=so.id, model_id=model.id,
                    color="white", size=size, quantity=qty,
                    unit_price=price, printing_required=False,
                ))
                total += qty * price
            so.total_amount = total

        # ----- Legacy models import (if CSV snapshot exists) -----
        created_models, created_sizes, created_collections = _import_legacy_models(db, admin)
        if created_models or created_sizes or created_collections:
            print(
                "Legacy import: "
                f"models={created_models}, sizes={created_sizes}, collections={created_collections}"
            )

        db.commit()
        print("Seed completed.")
    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
