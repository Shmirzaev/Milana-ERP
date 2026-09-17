from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password
from app.core.signing import sign_path
from app.models import Role, User
from app.tests.conftest import TestSessionLocal, test_engine


@pytest.fixture
def model_file_urls(tmp_path, monkeypatch):
    import app.main as main

    Image.new("RGB", (8, 8), "blue").save(tmp_path / "private.png")
    monkeypatch.setattr(main, "_MODEL_FILES_ROOT", str(tmp_path.resolve()))
    monkeypatch.setattr(main, "_MODEL_THUMBS_ROOT", str((tmp_path / "thumbs").resolve()))
    return (
        "/storage/model-files/private.png",
        "/storage/model-files/thumb/private.png?size=160",
    )


@pytest.fixture
def file_user(client):
    password = "SyntheticFileUser!2026"
    with TestSessionLocal() as db:
        role = Role(name="File viewer", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="File viewer",
            email="file-viewer@example.com",
            password_hash=hash_password(password),
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = user.id
    login = client.post(
        "/api/auth/login-json",
        json={"email": "file-viewer@example.com", "password": password, "factory_code": "MIL"},
    )
    assert login.status_code == 200, login.text
    return user_id, client.cookies.get(settings.AUTH_COOKIE_NAME)


def _auth_headers(client, token, transport):
    client.cookies.clear()
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
        return {}
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_active_user_can_read_model_files(client, file_user, model_file_urls, transport):
    _, token = file_user
    headers = _auth_headers(client, token, transport)
    for url in model_file_urls:
        response = client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("image/")


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("revocation", ["disabled", "deleted", "credentials_rotated"])
def test_revoked_user_cannot_read_model_files(
    client, file_user, model_file_urls, transport, revocation,
):
    user_id, token = file_user
    headers = _auth_headers(client, token, transport)
    # Warm the thumbnail cache too: a cached file must still require current auth.
    for url in model_file_urls:
        assert client.get(url, headers=headers).status_code == 200

    with TestSessionLocal() as db:
        user = db.get(User, user_id)
        if revocation == "disabled":
            user.is_active = False
        elif revocation == "deleted":
            db.delete(user)
        else:
            user.tokens_valid_from = datetime.fromtimestamp(decode_token(token)["iat"] + 1, timezone.utc)
        db.commit()

    assert client.get("/api/auth/me", headers=headers).status_code == 401
    for url in model_file_urls:
        response = client.get(url, headers=headers)
        assert response.status_code == 401, response.text
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("credential", ["missing", "invalid", "expired"])
def test_model_files_reject_missing_invalid_or_expired_cookie(client, file_user, model_file_urls, credential):
    user_id, _ = file_user
    client.cookies.clear()
    if credential == "invalid":
        client.cookies.set(settings.AUTH_COOKIE_NAME, "invalid-token")
    elif credential == "expired":
        token = create_access_token(user_id, extra={"exp": int(datetime.now(timezone.utc).timestamp()) - 60})
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    for url in model_file_urls:
        assert client.get(url).status_code == 401


def test_new_token_after_credential_rotation_can_read_model_files(client, file_user, model_file_urls):
    user_id, _ = file_user
    now = datetime.now(timezone.utc)
    with TestSessionLocal() as db:
        db.get(User, user_id).tokens_valid_from = now - timedelta(seconds=30)
        db.commit()
    old_token = create_access_token(user_id, extra={"iat": int((now - timedelta(minutes=1)).timestamp())})
    for token, expected in [(old_token, 401), (create_access_token(user_id), 200)]:
        headers = _auth_headers(client, token, "cookie")
        for url in model_file_urls:
            assert client.get(url, headers=headers).status_code == expected


def test_model_auth_releases_connection_before_reading_files(client, file_user, model_file_urls, monkeypatch):
    import app.main as main

    original = main._model_file_path_if_exists

    def checked_path(name):
        assert test_engine.pool.checkedout() == 0
        return original(name)

    monkeypatch.setattr(main, "_model_file_path_if_exists", checked_path)
    for url in model_file_urls:
        assert client.get(url).status_code == 200


def test_signed_model_url_does_not_replace_session_auth(client, model_file_urls):
    for url in model_file_urls:
        assert client.get(sign_path(url)).status_code == 401


def test_sales_attachment_signed_link_policy_is_preserved(client, file_user, tmp_path, monkeypatch):
    import app.main as main

    document = tmp_path / "attachment.txt"
    document.write_text("synthetic attachment", encoding="utf-8")
    monkeypatch.setattr(main, "_SALES_ORDER_FILES_ROOT", str(tmp_path.resolve()))
    path = "/storage/sales-order-files/attachment.txt"
    signed_url = sign_path(path)
    user_id, _ = file_user
    with TestSessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()

    # Signed sales links are bearer capabilities, independent of the session.
    assert client.get(signed_url).status_code == 200
    client.cookies.clear()
    assert client.get(signed_url).text == "synthetic attachment"
    assert client.get(path).status_code == 403
    assert client.get(sign_path(path, ttl_seconds=-60)).status_code == 403
    assert client.get(signed_url + "tampered").status_code == 403
