from sqlalchemy import event, select

from app.db.session import SessionLocal
from app.models import Model, ModelSize
from app.models import PayrollQrLabel, PayrollRecord, SewingFlow
from app.tests.test_payroll import _create_employee


def _model(code, sizes=(), *, family=None, scope="standard", legacy=False, camel_case=False):
    details = {"legacy_import": True} if legacy else {}
    if family is not None:
        details["general"] = {"modelNo" if camel_case else "model_no": family}
    with SessionLocal() as db:
        row = Model(code=code, name="Process QR size fixture", catalog_scope=scope,
                    factory_code="ECO" if scope == "usluga" else "MIL", details_json=details)
        db.add(row)
        db.flush()
        for size in sizes:
            db.add(ModelSize(model_id=row.id, size=size, measurement_json={"chest": 92}))
        db.commit()
        return row.id


def _resolve(client, headers, mid, resolution, sizes):
    response = client.get(f"/api/models/{mid}/process-qr-sizes", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"model_id": mid, "sizes": sizes, "resolution": resolution}
    return response


def test_own_sizes_override_conflicting_family_and_are_clean_unique_natural(client, auth_headers):
    mid = _model("QR-OWN-1", [" 10 ", "2", "2", " ", "12", "A10", "A2"], family="QR-OWN")
    _model("QR-OWN-2", ["48"], family="QR-OWN")
    _model("QR-OWN-3", ["50"], family="QR-OWN")
    _resolve(client, auth_headers, mid, "own", ["2", "10", "12", "A2", "A10"])


def test_xj3152_empty_variants_inherit_only_populated_sibling(client, auth_headers):
    targets = [
        _model("XJ3152-5412"),
        _model("XJ3152-5413"),
        _model("XJ3152-V5410", family="XJ3152"),
        _model("XJ3152-V5411", family="XJ3152", camel_case=True),
    ]
    _model("XJ3152-5416", ["58", "54", "48", "52", "50", "56"])
    for mid in targets:
        _resolve(client, auth_headers, mid, "inherited", ["48", "50", "52", "54", "56", "58"])


def test_matching_family_sets_ignore_order_duplicates_and_empty_rows(client, auth_headers):
    mid = _model("QR-SAME-1", [" ", ""], family="QR-SAME")
    _model("QR-SAME", ["50", "48"], family="QR-SAME")  # Base model is a valid donor.
    _model("QR-SAME-2", [" 48 ", "50", "48", ""], family="qr-same")
    _model("QR-SAME-3", family="QR-SAME")
    _resolve(client, auth_headers, mid, "inherited", ["48", "50"])


def test_conflicting_family_sets_return_no_sizes(client, auth_headers):
    mid = _model("QR-CONFLICT-1", family="QR-CONFLICT")
    _model("QR-CONFLICT-2", ["48", "50"], family="QR-CONFLICT")
    _model("QR-CONFLICT-3", ["48", "50", "52"], family="QR-CONFLICT")
    _resolve(client, auth_headers, mid, "conflict", [])


def test_missing_family_does_not_use_prefix_or_similar_name(client, auth_headers):
    mid = _model("QR-EXACT-1", family="QR-EXACT")
    _model("QR-EXACT-2", [" "], family="QR-EXACT")
    _model("QR-EXACT-OTHER-1", ["48"], family="QR-EXACT-OTHER")
    _model("UNRELATED-1", ["50"], family="UNRELATED")
    _resolve(client, auth_headers, mid, "missing", [])


def test_scope_and_internal_imports_cannot_supply_sizes(client, auth_headers):
    mid = _model("QR-SCOPE-1", family="QR-SCOPE")
    service = _model("SERVICE-SCOPE-1", ["50"], family="QR-SCOPE", scope="usluga")
    internal = _model("IMPORT-SCOPE-1", ["52"], family="QR-SCOPE", legacy=True)
    _resolve(client, auth_headers, mid, "missing", [])
    # Supplying a query argument cannot override the standard catalog dependency.
    response = client.get(f"/api/models/{service}/process-qr-sizes?catalog_scope=usluga", headers=auth_headers)
    assert response.status_code == 404
    assert client.get(f"/api/models/{service}", headers=auth_headers).status_code == 404
    _model("QR-SCOPE-2", ["48"], family="QR-SCOPE")
    _resolve(client, auth_headers, mid, "inherited", ["48"])
    # Like model detail, an internal row can expose its own sizes, but cannot inherit.
    _resolve(client, auth_headers, internal, "own", ["52"])
    empty_internal = _model("IMPORT-SCOPE-2", family="QR-SCOPE", legacy=True)
    _resolve(client, auth_headers, empty_internal, "missing", [])


def test_size_resolution_requires_authentication_and_existing_model(client, auth_headers):
    mid = _model("QR-AUTH-1", ["48"])
    response = client.get(f"/api/models/{mid}/process-qr-sizes")
    assert response.status_code in {401, 403}
    assert client.get("/api/models/2147483647/process-qr-sizes", headers=auth_headers).status_code == 404


def test_resolution_is_read_only_and_keeps_model_detail_rows_unchanged(client, auth_headers):
    mid = _model("QR-READONLY-1", family="QR-READONLY")
    donor = _model("QR-READONLY-2", [" 50 ", "48", "48"], family="QR-READONLY")
    before_details = {
        key: client.get(f"/api/models/{key}", headers=auth_headers).json()
        for key in (mid, donor)
    }
    with SessionLocal() as db:
        before_models = db.execute(select(Model.__table__).order_by(Model.id)).all()
        before_sizes = db.execute(select(ModelSize.__table__).order_by(ModelSize.id)).all()
        engine = db.get_bind()
    statements = []

    def capture_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        _resolve(client, auth_headers, mid, "inherited", ["48", "50"])
        _resolve(client, auth_headers, donor, "own", ["48", "50"])
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)
    assert statements
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    with SessionLocal() as db:
        assert db.execute(select(Model.__table__).order_by(Model.id)).all() == before_models
        assert db.execute(select(ModelSize.__table__).order_by(ModelSize.id)).all() == before_sizes
    for key in (mid, donor):
        response = client.get(f"/api/models/{key}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == before_details[key]
    assert before_details[mid]["sizes"] == []
    assert [row["size"] for row in before_details[donor]["sizes"]] == [" 50 ", "48", "48"]


def test_inherited_size_issues_and_scans_through_existing_payroll_with_snapshot(client, auth_headers):
    mid = _model("XJ3152-5412")
    donor = _model("XJ3152-5416", ["58", "54", "48", "52", "50", "56"])
    resolved = _resolve(client, auth_headers, mid, "inherited", ["48", "50", "52", "54", "56", "58"])
    size = resolved.json()["sizes"][0]
    employee = _create_employee(client, auth_headers, "Inherited size worker")
    with SessionLocal() as db:
        flow = SewingFlow(factory_code="MIL", code="QR-SIZE-TEST", name="QR size test line")
        db.add(flow)
        db.commit()
        flow_id = flow.id
    rows = [{
        "label_uid": f"PY:MAN:{mid}:SIZE-TEST:SEW-1:MIL:QR-SIZE-TEST:{size}:{copy}",
        "model_id": mid,
        "model_code": "XJ3152-5412",
        "production_no": f"MAN-{mid}-SIZE-TEST",
        "batch_no": "SIZE-TEST",
        "cutting_passport_no": "SIZE-TEST",
        "operation_section": "sewing",
        "operation_code": "SEW-1",
        "operation_name": "Inherited size sewing",
        "sewing_flow_id": flow_id,
        "sewing_line_code": "QR-SIZE-TEST",
        "sewing_line_name": "QR size test line",
        "size": size,
        "copy_index": copy,
        "quantity": 12,
        "rate_per_piece": 250,
        "currency": "UZS",
    } for copy in (1, 2)]
    issued = client.post("/api/payroll/qr-labels/issue", json={"labels": rows}, headers=auth_headers)
    assert issued.status_code == 200, issued.text
    assert issued.json()["created_count"] == 2
    tokens = [row["qr_token"] for row in issued.json()["labels"]]
    scanned = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                          json={"token": tokens[0], "employee_id": employee["id"]})
    assert scanned.status_code == 201, scanned.text
    assert scanned.json()["work"]["size"] == size
    assert scanned.json()["work"]["sewing_flow_id"] == flow_id
    assert scanned.json()["record"]["factory_code"] == "MIL"
    assert float(scanned.json()["record"]["rate_per_piece"]) == 250
    assert float(scanned.json()["record"]["total_amount"]) == 3000

    # Catalog changes do not rewrite already-issued work or its payable snapshot.
    with SessionLocal() as db:
        db.query(ModelSize).filter(ModelSize.model_id == donor).delete()
        db.commit()
    _resolve(client, auth_headers, mid, "missing", [])
    changed = {**rows[1], "size": "CLIENT-OVERRIDE", "quantity": 999, "rate_per_piece": 1}
    replay = client.post("/api/payroll/qr-labels/issue", json={"labels": [changed]}, headers=auth_headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["created_count"] == 0
    assert replay.json()["existing_count"] == 1
    assert replay.json()["labels"][0]["qr_token"] == tokens[1]
    snapshot_scan = client.post("/api/payroll/records", headers=auth_headers, json={
        "employee_id": employee["id"],
        "quantity": 999,
        "rate_per_piece": 1,
        "work": {**changed, "label_id": rows[1]["label_uid"]},
    })
    assert snapshot_scan.status_code == 201, snapshot_scan.text
    record = snapshot_scan.json()
    assert record["factory_code"] == "MIL"
    assert record["model_id"] == mid
    assert record["raw_work_json"]["size"] == size
    assert record["raw_work_json"]["sewing_flow_id"] == flow_id
    assert float(record["quantity"]) == 12
    assert float(record["rate_per_piece"]) == 250
    assert float(record["total_amount"]) == 3000
    with SessionLocal() as db:
        labels = db.query(PayrollQrLabel).filter(PayrollQrLabel.model_id == mid).all()
        records = db.query(PayrollRecord).filter(PayrollRecord.model_id == mid).all()
        assert len(labels) == len(records) == 2
        assert all(row.factory_code == "MIL" and row.status == "scanned" and row.size == size for row in labels)
        assert all(row.production_order_id is None and row.production_batch_id is None for row in labels)
        assert db.query(ModelSize).filter(ModelSize.model_id == mid).count() == 0
