import os
import shutil
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure SQLite for tests *before* importing app
_tmpdir = tempfile.mkdtemp(prefix="erp-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["BARCODE_STORAGE_DIR"] = os.path.join(_tmpdir, "barcodes")
os.environ["SALES_ORDER_FILES_DIR"] = os.path.join(_tmpdir, "sales_order_files")
os.environ["MODEL_FILES_DIR"] = os.path.join(_tmpdir, "model_files")
os.environ["JWT_SECRET"] = "test-secret"
os.environ["FILE_SIGNING_SECRET"] = "test-file-signing-secret-abcdefghijklmnopqrstuvwxyz"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["INTEGRATION_1C_TOKEN"] = "test-1c-token"
os.environ["ATTENDANCE_INTEGRATION_TOKEN"] = "test-attendance-token"
os.environ["ATTENDANCE_INTEGRATION_FACTORY_CODE"] = "MIL"
os.environ["ATTENDANCE_PHOTOS_DIR"] = os.path.join(_tmpdir, "attendance_photos")
os.environ["INITIAL_ADMIN_EMAIL"] = "admin@example.com"
os.environ["INITIAL_ADMIN_PASSWORD"] = "test-admin-password-123!"
os.environ["SEED_DEMO_USERS"] = "true"
os.environ["SEED_SAMPLE_DATA"] = "true"
os.environ["IMPORT_LEGACY_MODELS"] = "false"
_test_db_path = os.path.join(_tmpdir, "test.db")
_baseline_db_path = os.path.join(_tmpdir, "baseline.db")

from fastapi.testclient import TestClient

from app.main import app
from app.db import session as session_module
from app.db.base import Base

_original_engine = session_module.engine


# Swap engine to SQLite (sync) — adjust to use StaticPool for shared in-memory if needed
test_engine = create_engine(
    os.environ["DATABASE_URL"], connect_args={"check_same_thread": False}, future=True,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Patch the app's SessionLocal to use the test engine
session_module.engine = test_engine
session_module.SessionLocal = TestSessionLocal


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
    _original_engine.dispose()
    shutil.copyfile(_test_db_path, _baseline_db_path)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolate_database_changes():
    """Restore the seeded SQLite snapshot before every independent test.

    A file snapshot supports workflows that intentionally create independent
    sessions or call ``rollback()``; an outer transaction does not.
    """
    test_engine.dispose()
    _original_engine.dispose()
    shutil.copyfile(_baseline_db_path, _test_db_path)
    yield


@pytest.fixture(autouse=True)
def reset_shared_counter_store():
    from app.core.shared_store import reset_shared_counter_store_for_tests

    reset_shared_counter_store_for_tests()
    yield
    reset_shared_counter_store_for_tests()


@pytest.fixture(autouse=True)
def clear_attendance_mirror():
    from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson

    db = TestSessionLocal()
    try:
        db.query(AttendanceEvent).delete()
        db.query(AttendancePerson).delete()
        db.query(AttendanceDevice).delete()
        db.commit()
    finally:
        db.close()
    yield


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
