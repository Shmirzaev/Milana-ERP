"""OPS09 disposable HTTP fixture: actual app/auth/labels, fresh test SQLite only."""
import json
import importlib.util
import os
from pathlib import Path
import secrets

if os.environ.get("ACCEPTANCE_CSP_FIXTURE") != "1":
    raise SystemExit("Set ACCEPTANCE_CSP_FIXTURE=1 for the disposable acceptance fixture")

from app.tests.conftest import TestSessionLocal, test_engine
from app.core.config import settings
from app.db.base import Base
from app.db.seed import seed
from app.main import app
from app.core.proxy_trust import client_ip, effective_request_scheme
from starlette.requests import Request
from app.schemas import ModelImage
from app.tests.test_package_label_query_growth import _package_case
from app.tests.test_production_flow import _create_bundle_for_scan, _VALID_PNG
from fastapi.testclient import TestClient
import uvicorn

assert test_engine.dialect.name == "sqlite"
assert Path(test_engine.url.database).parent.name.startswith("erp-test-")
Base.metadata.create_all(test_engine)
seed()
# This is the test harness's metadata-created SQLite fixture, not a migration test.
from alembic import command
from app.main import _alembic_config
command.stamp(_alembic_config(), "head")
client = TestClient(app)
login = client.post("/api/auth/token", data={
    "username": settings.INITIAL_ADMIN_EMAIL, "password": settings.INITIAL_ADMIN_PASSWORD,
})
assert login.status_code == 200
headers = {"Authorization": "Bearer " + login.json()["access_token"]}
bundle = _create_bundle_for_scan(client, headers)
with TestSessionLocal() as db:
    package_ids, _ = _package_case(db, 6)
    for picture in db.query(ModelImage).filter(ModelImage.file_name.like("PERF12%")):
        picture.file_data = _VALID_PNG
    db.commit()
manifest = {
    "bundle": f"/api/bundles/{bundle['id']}/label",
    "packages": "/api/packages/label-sheet/by-ids?ids=" + ",".join(map(str, package_ids)),
    "login_email": settings.INITIAL_ADMIN_EMAIL,
    "database": "fresh temporary SQLite",
}
for label in ("bundle", "packages"):
    result = client.get(manifest[label], headers=headers)
    assert result.status_code == 200, f"Fixture {label} response status {result.status_code}"
output = Path(os.environ["ACCEPTANCE_CSP_OUTPUT"])
output.mkdir(parents=True, exist_ok=True)
(output / "manifest.json").write_text(json.dumps(manifest, indent=2))

# Test-only hosted configuration exercises production cookie/startup behavior.
settings.ENV = "production"
settings.DEBUG = False
settings.JWT_SECRET = secrets.token_hex(32)
settings.FILE_SIGNING_SECRET = secrets.token_hex(32)
settings.SHARED_STORE_URL = f"sqlite:///{Path(test_engine.url.database).parent / 'counters.db'}"
settings.CORS_ORIGINS = "https://127.0.0.1:18443"
settings.SEED_DEMO_USERS = False
settings.SEED_SAMPLE_DATA = False
os.environ["TRUSTED_PROXY_CIDRS"] = "127.0.0.1/32"
os.environ["FORWARDED_ALLOW_IPS"] = ""
from app.core import shared_store
shared_store._store = None
async def observed_application(scope, receive, send):
    if scope["type"] != "http":
        return await app(scope, receive, send)
    request = Request(scope)
    from app.main import _rate_limit_client_key
    observations = {
        "peer": scope["client"][0], "client": client_ip(request),
        "rate-client": _rate_limit_client_key(request), "scheme": effective_request_scheme(request),
    }

    async def observed_send(message):
        if message["type"] == "http.response.start":
            message["headers"] = [*message["headers"], *[
                (f"x-acceptance-{key}".encode(), value.encode()) for key, value in observations.items()
            ]]
        await send(message)
    await app(scope, receive, observed_send)


# Reuse the production HAProxy forwarding policy; only isolated ports differ.
source = Path(__file__).resolve().parents[3] / "deploy/slotctl.py"
spec = importlib.util.spec_from_file_location("acceptance_slotctl", source)
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
deployment.ROLES["backend"].update(stable=19080, blue=18081)
configuration = deployment.proxy_config("backend", "blue")
configuration = configuration.replace("bind 0.0.0.0:19080", "bind 127.0.0.1:19080")
(output / "haproxy.cfg").write_text(configuration)
uvicorn.run(observed_application, host="127.0.0.1", port=18081,
            proxy_headers=False, access_log=False, log_level="warning")
