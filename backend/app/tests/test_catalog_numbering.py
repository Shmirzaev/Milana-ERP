from app.models import Model, SystemSetting
from app.services.numbering import next_model_no, next_model_variant_no
from app.tests.conftest import TestSessionLocal


def test_variant_stream_skips_legacy_codes_and_metadata_without_following_outliers():
    with TestSessionLocal() as db:
        db.add_all([
            Model(code="XJ3200-06455", name="Legacy numeric suffix"),
            Model(code="SPECIAL", name="Explicit variant", details_json={"general": {"variant_no": "V6456"}}),
            Model(code="PJ1164-43891", name="Historical outlier"),
        ])
        db.commit()
        assert next_model_variant_no(db) == "V-6457"
        assert next_model_variant_no(db, reserve=True) == "V-6457"
        db.commit()
        assert next_model_variant_no(db) == "V-6458"


def test_model_prefix_stream_skips_existing_variants_and_keeps_other_prefixes():
    with TestSessionLocal() as db:
        db.add_all([
            Model(code="ХJ-3201-123", name="Legacy Cyrillic family"),
            Model(code="SPECIAL-BASE", name="Explicit family", details_json={"general": {"model_no": "XJ3202"}}),
            Model(code="XJ7641", name="Historical outlier"),
        ])
        db.commit()
        assert next_model_no(db, "XJ") == "XJ3203"
        assert next_model_no(db, "PJ") == "PJ1253"
        assert next_model_no(db, "XJ", reserve=True) == "XJ3203"
        assert next_model_no(db, "PJ", reserve=True) == "PJ1253"
        db.commit()
        assert next_model_no(db, "XJ") == "XJ3204"
        assert next_model_no(db, "PJ") == "PJ1254"


def test_model_create_reserves_server_number_even_after_stale_preview(client, auth_headers):
    preview = client.get("/api/models/next-number?prefix=XJ", headers=auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["model_no"] == "XJ3201"
    payload = {"code": "XJ3201", "automatic_model_prefix": "XJ", "name": "Auto model",
               "details_json": {"general": {"model_no": "XJ3201"}}}
    first = client.post("/api/models", json=payload, headers=auth_headers)
    second = client.post("/api/models", json=payload, headers=auth_headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["code"] == "XJ3201"
    assert second.json()["code"] == "XJ3202"
    assert second.json()["details_json"]["general"]["model_no"] == "XJ3202"
    assert client.delete(f"/api/models/{second.json()['id']}", headers=auth_headers).status_code == 204
    assert client.get("/api/models/next-number?prefix=XJ", headers=auth_headers).json()["model_no"] == "XJ3203"


def test_number_preview_is_read_only_and_failed_create_does_not_consume(client, auth_headers):
    with TestSessionLocal() as db:
        before = db.query(SystemSetting).count()
    assert client.get("/api/models/next-number?prefix=XJ", headers=auth_headers).status_code == 200
    invalid = client.post("/api/models", headers=auth_headers, json={
        "code": "ignored", "name": "Invalid", "automatic_model_prefix": "XJ",
        "details_json": {"general": {"variant_no": "V-1"}},
    })
    assert invalid.status_code == 400
    with TestSessionLocal() as db:
        assert db.query(SystemSetting).count() == before
        assert next_model_no(db, "XJ") == "XJ3201"
    assert client.get("/api/models/next-number?prefix=ZZ", headers=auth_headers).status_code == 400
    assert client.get("/api/models/next-number?prefix=XJ").status_code == 401
