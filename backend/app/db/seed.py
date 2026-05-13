"""Seed initial data: departments, roles, admin user, sample catalog, sample orders."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models  # noqa
from app.models import (
    Role, Department, User, Customer, Supplier, Warehouse, Item,
    Brand, Collection, Model, ModelSize, ModelColor, ModelBOM,
    SalesOrder, SalesOrderItem, StockBatch, SewingFlow,
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


def seed():
    Base.metadata.create_all(bind=engine)
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
