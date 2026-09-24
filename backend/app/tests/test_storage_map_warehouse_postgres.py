"""Optional PostgreSQL concurrency coverage for warehouse-map placement.

Set WAREHOUSE_MAP_TEST_DATABASE_URL to a disposable PostgreSQL database to run.
The test creates and drops a uniquely named schema; it never touches app data.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Model, Package, ProductionOrder
from app.services.packages import _prepare_storage_map_placement


@pytest.mark.skipif(
    not os.environ.get("WAREHOUSE_MAP_TEST_DATABASE_URL"),
    reason="set WAREHOUSE_MAP_TEST_DATABASE_URL to a disposable PostgreSQL database",
)
def test_concurrent_different_model_moves_serialize_and_rollback():
    database_url = os.environ["WAREHOUSE_MAP_TEST_DATABASE_URL"]
    schema = f"wm_guard_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    options = f"-csearch_path={schema}"
    test_engine = create_engine(database_url, connect_args={"options": options}, future=True)
    try:
        import app.models  # noqa: F401 - register every metadata dependency

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine, expire_on_commit=False)
        marker = uuid4().hex[:12].upper()
        with Session.begin() as db:
            models = [
                Model(code=f"PG-MOVE-{marker}-{index}", name=f"PG move model {index}")
                for index in (1, 2)
            ]
            db.add_all(models)
            db.flush()
            orders = [
                ProductionOrder(
                    production_no=f"PG-PO-{marker}-{index}",
                    production_type="branded_stock",
                    model_id=model.id,
                    planned_quantity=1,
                )
                for index, model in enumerate(models, start=1)
            ]
            db.add_all(orders)
            db.flush()
            packages = [
                Package(
                    package_no=f"PG-PKG-{marker}-{index}",
                    barcode=f"PG-BC-{marker}-{index}",
                    production_order_id=order.id,
                    model_id=model.id,
                    color="Blue",
                    total_quantity=1,
                    capacity=60,
                    status="received_in_storage",
                    storage_cell=source,
                    storage_shelf="S1",
                )
                for index, (model, order, source) in enumerate(
                    zip(models, orders, ("A-01", "C-01")), start=1
                )
            ]
            db.add_all(packages)
            db.flush()
            package_ids = [int(package.id) for package in packages]

        start_together = Barrier(2)

        def move_to_same_cell(package_id: int) -> str:
            with Session() as db:
                package = db.query(Package).filter(Package.id == package_id).one()
                start_together.wait(timeout=10)
                try:
                    locked = _prepare_storage_map_placement(
                        db,
                        [package],
                        storage_cell="B-01",
                        allow_mixed_models=False,
                        enforce_model_guard=True,
                    )
                    locked[0].storage_cell = "B-01"
                    locked[0].storage_shelf = "S1"
                    db.commit()
                    return "moved"
                except HTTPException:
                    db.rollback()
                    return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(move_to_same_cell, package_ids))

        assert sorted(results) == ["moved", "rejected"]
        with Session() as db:
            packages = db.query(Package).filter(Package.id.in_(package_ids)).all()
            assert sum(package.storage_cell == "B-01" for package in packages) == 1
            assert sum(package.storage_cell in {"A-01", "C-01"} for package in packages) == 1
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()

