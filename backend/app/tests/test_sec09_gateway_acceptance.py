"""SEC09-PROXY closing evidence through the deployment HAProxy forwarding policy."""
from __future__ import annotations

from contextlib import contextmanager
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
import time
from uuid import uuid4

from alembic import command
import httpx
import pytest
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
import uvicorn

from app import main
from app.api.routes import auth
from app.core.config import settings
from app.core.proxy_trust import effective_request_scheme, validate_proxy_runtime_configuration
from app.core.security import hash_password
from app.db.session import get_db
from app.schemas import Department, Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401


@contextmanager
def _http_server(application):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        # Match the supported Uvicorn command's environment-controlled trust,
        # rather than masking a forwarding regression in a test transport.
        config = uvicorn.Config(application, log_level="error", lifespan="off", access_log=False)
        assert config.forwarded_allow_ips == ""
        server = uvicorn.Server(config)
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline, "Uvicorn did not start"
                time.sleep(.01)
            yield listener.getsockname()[1]
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), "Uvicorn did not stop"


@pytest.fixture(params=["sqlite", "postgresql"])
def gateway(request, tmp_path, monkeypatch):
    executable = shutil.which("haproxy")
    if executable is None:
        if os.environ.get("MILANA_REQUIRE_TEST_PG") == "1":
            pytest.fail("SEC09 closing test requires haproxy in the isolated test container")
        pytest.skip("Install the HAProxy test prerequisite; the #322 evidence run must not skip")
    factory = TestSessionLocal
    if request.param == "postgresql":
        database = request.getfixturevalue("postgres_migrations")
        command.upgrade(database.config, "head")
        factory = sessionmaker(bind=database.engine, expire_on_commit=False)
    unique = uuid4().hex
    email = f"gateway-{unique}@example.com"
    password = "IsolatedGatewayFixture123!"
    with factory() as db:
        role = Role(name=f"Gateway {unique}", permissions=["*"])
        department = Department(name=f"Gateway {unique}", code=f"G{unique[:6]}")
        db.add_all([role, department])
        db.flush()
        db.add(User(name="Gateway fixture", email=email, password_hash=hash_password(password),
                    role_id=role.id, department_id=department.id, factory_code="MIL", is_active=True))
        db.commit()

    def database_session():
        with factory() as db:
            yield db

    monkeypatch.setitem(main.app.dependency_overrides, get_db, database_session)
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "ENV", "test")
    for marker in ("SPACE_ID", "SPACE_HOST", "HF_SPACE_ID", "HF_SPACE_HOST", "RENDER",
                   "RENDER_EXTERNAL_HOSTNAME", "VERCEL", "PUBLIC_DEPLOYMENT"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    validate_proxy_runtime_configuration(strict_security_required=True)

    async def observed_application(scope, receive, send):
        if scope["type"] != "http":
            return await main.app(scope, receive, send)
        incoming = Request(scope)
        observed = {
            "peer": scope["client"][0],
            "client": auth._client_ip(incoming),
            "rate-client": main._rate_limit_client_key(incoming),
            "rate-identity": main._rate_limit_identity_key(incoming),
            "scheme": effective_request_scheme(incoming),
        }

        async def observed_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], *[
                    (f"x-acceptance-{key}".encode(), value.encode()) for key, value in observed.items()
                ]]
            await send(message)
        await main.app(scope, receive, observed_send)

    source = Path(__file__).resolve().parents[3] / "deploy/slotctl.py"
    module_spec = importlib.util.spec_from_file_location("acceptance_slotctl", source)
    deployment = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(deployment)
    with _http_server(observed_application) as port, socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        proxy_port = reservation.getsockname()[1]
        reservation.close()
        deployment.ROLES["backend"].update(stable=proxy_port, blue=port)
        configuration = deployment.proxy_config("backend", "blue")
        # Only listener address/ports differ: no application VM port is exposed
        # by this local fixture, and the deployment forwarding policy is intact.
        configuration = configuration.replace(f"bind 0.0.0.0:{proxy_port}", f"bind 127.0.0.1:{proxy_port}")
        config_path = tmp_path / "haproxy.cfg"
        config_path.write_text(configuration)
        subprocess.run([executable, "-c", "-f", str(config_path)], check=True, capture_output=True)
        with (tmp_path / "haproxy.log").open("w") as log:
            process = subprocess.Popen([executable, "-db", "-f", str(config_path)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 5
                while True:
                    assert process.poll() is None, "HAProxy exited during startup"
                    try:
                        with socket.create_connection(("127.0.0.1", proxy_port), timeout=.1):
                            break
                    except OSError:
                        assert time.monotonic() < deadline, "HAProxy did not start"
                        time.sleep(.02)
                yield {"direct": f"http://127.0.0.1:{port}", "proxy": f"http://127.0.0.1:{proxy_port}",
                       "email": email, "password": password, "database": request.param}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _client():
    # Distinct loopback source is intentionally NOT in TRUSTED_PROXY_CIDRS.
    return httpx.Client(transport=httpx.HTTPTransport(local_address="127.0.0.2"),
                        timeout=5, trust_env=False)


def test_real_gateway_client_identity_and_forwarded_chain_order(gateway):
    cases = [
        ("direct", [("X-Forwarded-For", "203.0.113.66"), ("X-Forwarded-Proto", "https")],
         "127.0.0.2", "http"),
        ("proxy", [("X-Forwarded-For", "203.0.113.66, 198.51.100.10"),
                   ("X-Forwarded-Proto", "http"), ("X-Forwarded-Proto", "https")],
         "127.0.0.2", "https"),
        ("proxy", [("X-Forwarded-For", "203.0.113.66"),
                   ("X-Forwarded-For", "198.51.100.10"),
                   ("X-Forwarded-Proto", "https"), ("X-Forwarded-Proto", "http")],
         "127.0.0.2", "http"),
        ("proxy", [("X-Forwarded-For", "198.51.100.10,,garbage")], "127.0.0.1", "http"),
    ]
    observations = []
    with _client() as client:
        for path, fields, expected_client, scheme in cases:
            response = client.get(gateway[path] + "/health", headers=fields)
            assert response.status_code == 200
            observed = {key: response.headers[f"x-acceptance-{key}"] for key in
                        ("peer", "client", "rate-client", "rate-identity", "scheme")}
            assert observed["peer"] == ("127.0.0.2" if path == "direct" else "127.0.0.1")
            assert observed["client"] == observed["rate-client"] == expected_client
            assert observed["rate-identity"] == f"ip:{expected_client}"
            assert observed["scheme"] == scheme
            assert ("strict-transport-security" in response.headers) == (scheme == "https")
            observations.append({"path": path, **observed})
    print(json.dumps({"SEC09-PROXY": gateway["database"], "observations": observations}))


def test_real_gateway_csrf_and_login_cookie_flags(gateway):
    host = "gateway.acceptance.test"
    cases = [("direct", "https", "https", False, 403),
             ("direct", "http", "https", False, 200),
             ("proxy", "https", "https", True, 200),
             ("proxy", "http", "http", False, 200)]
    for path, origin_scheme, forwarded_scheme, secure, expected in cases:
        with _client() as client:
            headers = [("Host", host), ("Origin", f"{origin_scheme}://{host}"), ("X-Forwarded-Proto", forwarded_scheme)]
            response = client.post(gateway[path] + "/api/auth/login-json", headers=headers,
                                   json={"email": gateway["email"], "password": gateway["password"],
                                         "factory_code": "MIL"})
            assert response.status_code == expected
            if expected == 403:
                assert "set-cookie" not in response.headers
                continue
            cookie = SimpleCookie()
            cookie.load(response.headers["set-cookie"])
            flags = {"secure": bool(cookie[settings.AUTH_COOKIE_NAME]["secure"]),
                     "httponly": bool(cookie[settings.AUTH_COOKIE_NAME]["httponly"]),
                     "samesite": cookie[settings.AUTH_COOKIE_NAME]["samesite"]}
            assert flags == {"secure": secure, "httponly": True, "samesite": "lax"}
            assert ("strict-transport-security" in response.headers) == secure
            print(json.dumps({"SEC09-PROXY": gateway["database"], "path": path, "cookie_flags": flags}))
