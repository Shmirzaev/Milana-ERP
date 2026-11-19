"""Serve this candidate with disposable local-only factory workflow fixtures.

Run from the worktree root with the test Python. Importing conftest first forces
an owned temporary SQLite database and temporary storage; no production access.
"""
import json
import os
from pathlib import Path
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Reuse this preview's isolated SQLite fixture")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "backend"))
    os.environ["ENV"] = "test"
    from app.tests.conftest import test_engine, TestSessionLocal
    from app.core.config import settings
    from app.core.security import hash_password
    from app.db.base import Base
    from app.db.seed import seed
    from app.schemas import User
    from app.tests.packaging_workflow_fixtures import seed_packaging_workflow
    from app.tests.factory_reports_fixture import build_factory_reports_fixture
    from app.tests.eco_fabric_fixture import make_eco_fabric_case

    settings.CORS_ORIGINS = "http://127.0.0.1:18933"
    output = root / "outputs/factory-qa"
    if args.resume:
        from sqlalchemy import create_engine
        from app.db import session as session_module
        facts = json.loads((output / "browser-fixture.json").read_text(encoding="utf-8"))
        database = Path(facts["database"]).resolve()
        assert database.is_file() and database.name == "test.db"
        assert database.parent.name.startswith("erp-test-")
        test_engine = create_engine(f"sqlite:///{database.as_posix()}", connect_args={"check_same_thread": False})
        TestSessionLocal.configure(bind=test_engine)
        session_module.engine = test_engine
        with TestSessionLocal() as db:
            assert db.get(User, facts["accounts"]["planner"]["id"]).email == facts["accounts"]["planner"]["email"]
        for field, folder in (("BARCODE_STORAGE_DIR", "barcodes"), ("MODEL_FILES_DIR", "model_files"),
                              ("SALES_ORDER_FILES_DIR", "sales_order_files")):
            setattr(settings, field, str(database.parent / folder))
        from app.main import app
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=18932, access_log=False)
        return
    Base.metadata.create_all(test_engine)
    seed()
    with TestSessionLocal.begin() as db:
        packaging = seed_packaging_workflow(db)
        reports = build_factory_reports_fixture(db)
    eco = make_eco_fabric_case(TestSessionLocal)
    accounts = {}
    with TestSessionLocal.begin() as db:
        for name, uid in [("planner", eco["planner"]), ("eco_operator", eco["operator"])]:
            actor = db.get(User, uid)
            actor.password_hash = hash_password("Factory-qa-only-2026!")
            accounts[name] = {"id": uid, "email": actor.email}
        for factory, facts in reports["factories"].items():
            actor = db.get(User, facts["user_id"])
            actor.password_hash = hash_password("Factory-qa-only-2026!")
            accounts[f"report_{factory}"] = {"id": actor.id, "email": actor.email}
    facts = {"packaging": packaging, "reports": reports,
             "eco": {key: value for key, value in eco.items() if not key.endswith("_headers")},
             "accounts": accounts, "database": test_engine.url.database}
    output.mkdir(parents=True, exist_ok=True)
    (output / "browser-fixture.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    # Only the disposable test engine may be used by this process.
    assert test_engine.url.drivername == "sqlite"
    from app.main import app
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18932, access_log=False)


if __name__ == "__main__":
    main()
