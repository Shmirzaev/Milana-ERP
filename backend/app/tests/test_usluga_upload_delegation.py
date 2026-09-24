import asyncio
from types import SimpleNamespace

from app.api.routes import usluga


def _eco_user():
    return SimpleNamespace(
        id=123,
        factory_code="ECO",
        session_factory_code="ECO",
        role=None,
        extra_permissions=[],
    )


def test_usluga_model_image_upload_preserves_eco_gate_and_catalog_scope(monkeypatch):
    calls = []

    async def fake_upload(mid, db, file, image_type, current, catalog_scope):
        calls.append((mid, db, file, image_type, current, catalog_scope))
        return {"file_url": "/synthetic.webp"}

    monkeypatch.setattr(usluga.catalog_routes, "upload_image", fake_upload)
    db = object()
    file = object()
    current = _eco_user()
    response = asyncio.run(usluga.upload_usluga_model_image(7, db, file, "model", current))

    assert response == {"file_url": "/synthetic.webp"}
    assert calls == [(7, db, file, "model", current, "usluga")]


def test_usluga_bom_photo_upload_preserves_eco_gate_and_catalog_scope(monkeypatch):
    calls = []

    async def fake_upload(mid, db, file, current, catalog_scope):
        calls.append((mid, db, file, current, catalog_scope))
        return {"file_url": "/synthetic.webp"}

    monkeypatch.setattr(usluga.catalog_routes, "upload_bom_photo", fake_upload)
    db = object()
    file = object()
    current = _eco_user()
    response = asyncio.run(usluga.upload_usluga_model_bom_photo(8, db, file, current))

    assert response == {"file_url": "/synthetic.webp"}
    assert calls == [(8, db, file, current, "usluga")]
