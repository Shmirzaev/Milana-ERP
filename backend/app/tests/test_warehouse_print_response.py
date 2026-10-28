"""Real middleware responses must preserve usable and narrowly scoped print CSP."""
from base64 import b64encode
from hashlib import sha256
import json
import os
from pathlib import Path

from app.tests.test_package_workflows import manual_body, stock_fingerprint
from app.tests.test_shipment_review import dispatch as dispatch, ship


def check_print(response, name):
    assert response.status_code == 200, response.text
    policy = response.headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in policy.split(";") if part.strip())
    expected_hash = b64encode(sha256(b"window.print()").digest()).decode("ascii")
    assert directives["default-src"] == "'none'"
    assert directives["script-src"] == f"'unsafe-hashes' 'sha256-{expected_hash}'"
    assert directives["script-src-elem"] == "'none'"
    assert directives["style-src"] == "'unsafe-inline'"
    assert directives["img-src"] == "'self' data: blob:"
    for key in ("object-src", "base-uri", "frame-ancestors", "form-action"):
        assert directives[key] == "'none'"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "window.print()" in response.text
    assert "<style>" in response.text
    # Optional isolated browser evidence; only synthetic test records are exported.
    if directory := os.environ.get("ERP_PRINT_QA_DIR"):
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{name}.json").write_text(json.dumps({
            "status": response.status_code, "headers": dict(response.headers), "body": response.text,
        }), encoding="utf-8")


def test_package_print_routes_preserve_scoped_policy_and_stock(client, auth_headers):
    client.headers["accept-encoding"] = "identity"
    created = client.post("/api/packages/manual-receipt", headers=auth_headers, json=manual_body())
    assert created.status_code == 201, created.text
    run = created.json()["print_run"]
    pid = run["package_ids"][0]
    before = stock_fingerprint()
    for name, path in (
        ("package-label", f"/api/packages/{pid}/label"),
        ("package-sheet", f"/api/packages/label-sheet/by-ids?ids={pid}"),
        ("print-run", f"/api/packages/print-runs/{run['id']}/label"),
    ):
        check_print(client.get(path, headers=auth_headers), name)
    assert stock_fingerprint() == before
    ordinary = client.get(f"/api/packages/{pid}", headers=auth_headers)
    assert "unsafe-inline" not in ordinary.headers["content-security-policy"]


def test_invoice_print_response_preserves_policy_in_all_languages(client, auth_headers, dispatch):
    client.headers["accept-encoding"] = "identity"
    ship(client, auth_headers, dispatch)
    for lang in ("en", "ru", "uz"):
        response = client.get(f"/api/shipments/{dispatch['shipment']}/invoice/print?lang={lang}", headers=auth_headers)
        check_print(response, f"invoice-{lang}")
        assert "<script>alert(1)</script>" not in response.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
