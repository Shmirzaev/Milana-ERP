import os
import shutil
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure SQLite for tests *before* importing app
_tmpdir = tempfile.mkdtemp(prefix="erp-test-")
_database_path = os.path.join(_tmpdir, "test.db")
_database_baseline_path = os.path.join(_tmpdir, "test-baseline.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_database_path}"
os.environ["BARCODE_STORAGE_DIR"] = os.path.join(_tmpdir, "barcodes")
os.environ["SALES_ORDER_FILES_DIR"] = os.path.join(_tmpdir, "sales_order_files")
os.environ["MODEL_FILES_DIR"] = os.path.join(_tmpdir, "model_files")
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FILE_SIGNING_SECRET"] = "test-file-signing-secret-abcdefghijklmnopqrstuvwxyz"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["INTEGRATION_1C_TOKEN"] = "test-1c-token"
os.environ["INITIAL_ADMIN_EMAIL"] = "admin@example.com"
os.environ["INITIAL_ADMIN_PASSWORD"] = "test-admin-password-123!"
os.environ["SEED_DEMO_USERS"] = "true"
os.environ["SEED_SAMPLE_DATA"] = "true"
os.environ["IMPORT_LEGACY_MODELS"] = "false"

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.db import session as session_module
from app.db.base import Base
from app.services import password_reset as password_reset_module


# Swap engine to SQLite (sync) — adjust to use StaticPool for shared in-memory if needed
test_engine = create_engine(
    os.environ["DATABASE_URL"], connect_args={"check_same_thread": False}, future=True,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Patch the app's SessionLocal to use the test engine
original_engine = session_module.engine
session_module.engine = test_engine
session_module.SessionLocal = TestSessionLocal
# These modules import the session globals while app is loading, before the
# replacements above. Keep every test writer on one disposable connection pool.
main_module.engine = test_engine
main_module.SessionLocal = TestSessionLocal
password_reset_module.SessionLocal = TestSessionLocal
original_engine.dispose()


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


from app.db.session import get_db
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    import app.models  # noqa: F401 - register all models
    Base.metadata.create_all(bind=test_engine)
    # Seed minimal data
    from app.db.seed import seed
    seed()
    test_engine.dispose()
    shutil.copyfile(_database_path, _database_baseline_path)
    yield
    test_engine.dispose()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def restore_seeded_database(setup_db):
    # Seeding takes several seconds, so restore the one-time seeded snapshot
    # instead of rebuilding the schema and seed data for every test.
    test_engine.dispose()
    shutil.copyfile(_database_baseline_path, _database_path)
    yield
    test_engine.dispose()


@pytest.fixture(autouse=True)
def reset_shared_counter_store():
    from app.core.shared_store import reset_shared_counter_store_for_tests

    reset_shared_counter_store_for_tests()
    yield
    reset_shared_counter_store_for_tests()


@pytest.fixture
def admin_token(client):
    r = client.post(
        "/api/auth/token",
        data={"username": "admin@example.com", "password": "test-admin-password-123!"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
