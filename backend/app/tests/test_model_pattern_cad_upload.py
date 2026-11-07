"""Opaque synthetic CAD fixtures prove transfer/storage, not Gemini compatibility."""
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.schemas import Model, ModelImage, User
from app.tests.conftest import TestSessionLocal


CAD_BYTES = b"SYNTHETIC QA CAD TRANSFER FIXTURE\x00\x01\xff\x80\r\nnot a real Gemini document"


@pytest.fixture
def cad_case(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_MODEL_FILES_ROOT", str(tmp_path))
    with TestSessionLocal() as db:
        marker = uuid4().hex
        actor = User(name="QA CAD uploader", email=f"cad-{marker}@example.invalid", password_hash="unused",
                     factory_code="ECO", extra_permissions=["modeling.models", "usluga.manage"], is_active=True)
        standard = Model(code=f"CAD-{marker}", name="QA CAD model", catalog_scope="standard")
        usluga = Model(code=f"CAD-S-{marker}", name="QA CAD service model", catalog_scope="usluga")
        db.add_all([actor, standard, usluga]); db.commit()
        token = create_access_token(actor.id, extra={"factory_code": "ECO"})
        return {"standard": standard.id, "usluga": usluga.id, "headers": {"Authorization": f"Bearer {token}"}, "dir": tmp_path}


def upload(client, case, *, scope="standard", filename="qa.gem", content=CAD_BYTES, mime="application/octet-stream", image_type="pattern"):
    prefix = "/api/usluga" if scope == "usluga" else "/api"
    return client.post(f"{prefix}/models/{case[scope]}/images/upload", headers=case["headers"],
                       files={"file": (filename, content, mime)}, data={"image_type": image_type} if image_type is not None else {})


@pytest.mark.parametrize("filename,mime", [("qa.gem", "application/octet-stream"), ("QA.GEMX", "application/octet-stream"),
                                           ("qa.gemx", "application/x-gemini"), ("qa.GEM", "text/plain"),
                                           ("../QA.GEMX", "image/png")])
@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_cad_upload_download_preserves_original_bytes_and_metadata(client, cad_case, filename, mime, scope):
    response = upload(client, cad_case, scope=scope, filename=filename, mime=mime)
    assert response.status_code == 201, response.text
    body = response.json()
    saved = cad_case["dir"] / body["file_url"].split("/")[-1]
    assert saved.name.startswith(f"model_{cad_case[scope]}_")
    assert saved.suffix == Path(filename).suffix.lower()
    assert saved.read_bytes() == CAD_BYTES
    assert len(list(cad_case["dir"].iterdir())) == 1  # no image conversion/thumbnail
    with TestSessionLocal() as db:
        image = db.get(ModelImage, body["id"])
        assert (image.model_id, image.image_type, image.file_name, image.content_type) == (cad_case[scope], "pattern", filename, "application/octet-stream")
        assert image.file_data is None
    downloaded = client.get(body["file_url"], headers=cad_case["headers"])
    assert downloaded.status_code == 200
    assert downloaded.content == CAD_BYTES
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert client.get(body["file_url"]).status_code == 401


@pytest.mark.parametrize("image_type", ["model", "material", None])
def test_cad_is_only_accepted_as_pattern(client, cad_case, image_type):
    response = upload(client, cad_case, image_type=image_type)
    assert response.status_code == 400, response.text
    assert not list(cad_case["dir"].iterdir())


@pytest.mark.parametrize("content", [b"", b"MZ" + b"\0" * 128, b"\x7fELF" + b"\0" * 128,
                                     b"#!/bin/sh\necho qa", b"<!DOCTYPE html><html>qa</html>",
                                     b"\xef\xbb\xbf  <HTML>qa</HTML>", b"<script>alert('qa')</script>"])
@pytest.mark.parametrize("ext", [".gem", ".gemx"])
def test_invalid_active_content_is_refused_without_files_or_rows(client, cad_case, content, ext):
    response = upload(client, cad_case, filename="qa" + ext, content=content)
    assert response.status_code == 400, response.text
    assert not list(cad_case["dir"].iterdir())
    with TestSessionLocal() as db:
        assert db.query(ModelImage).filter_by(model_id=cad_case["standard"]).count() == 0


def test_cad_over_twenty_mib_refuses_before_persistence(client, cad_case):
    response = upload(client, cad_case, content=b"Q" * (20 * 1024 * 1024 + 1))
    assert response.status_code == 400, response.text
    assert "20MB" in response.text
    assert not list(cad_case["dir"].iterdir())


def test_exact_twenty_mib_boundary_preserves_bytes(client, cad_case):
    content = b"Q" * (20 * 1024 * 1024)
    response = upload(client, cad_case, content=content)
    assert response.status_code == 201, response.text
    assert client.get(response.json()["file_url"], headers=cad_case["headers"]).content == content


def test_cad_does_not_expand_image_or_sales_attachment_uploads(client, cad_case, auth_headers):
    image = client.post(f"/api/models/{cad_case['standard']}/bom-photo/upload", headers=cad_case["headers"],
                        files={"file": ("qa.gemx", CAD_BYTES, "application/octet-stream")})
    assert image.status_code == 400, image.text
    document = client.post("/api/sales-orders/printing-attachments/upload", headers=auth_headers,
                           files={"file": ("qa.gem", CAD_BYTES, "application/octet-stream")})
    assert document.status_code == 400, document.text
    assert not list(cad_case["dir"].iterdir())


def test_existing_scope_permissions_and_filename_guards_remain(client, cad_case):
    bad_scope = client.post(f"/api/models/{cad_case['usluga']}/images/upload", headers=cad_case["headers"],
                            files={"file": ("qa.gem", CAD_BYTES)}, data={"image_type": "pattern"})
    assert bad_scope.status_code == 404
    assert upload(client, cad_case, filename="qa.gem.exe").status_code == 400
    with TestSessionLocal() as db:
        actor = db.query(User).filter(User.email.like("cad-%@example.invalid")).one()
        actor.extra_permissions = []; db.commit()
    assert upload(client, cad_case).status_code == 403
    assert not list(cad_case["dir"].iterdir())
