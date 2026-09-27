from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import event

from app.api.routes import fabric_scans
from app.models.fabric_scan import FabricScan
from app.tests.conftest import TestSessionLocal


def test_duplicate_scan_projection_preserves_response(monkeypatch):
    scan_time = datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc)
    with TestSessionLocal() as db:
        existing = FabricScan(
            department="CUT",
            report_date=date(2026, 9, 22),
            batch_id=123,
            roll_number=4,
            direction="received",
            fabric_name="Cotton jersey",
            batch_no="BATCH-123",
            color="navy",
            operator_id=9,
            operator_name="Cutting operator",
            scanned_at=scan_time,
        )
        db.add(existing)
        db.commit()
        existing_id = int(existing.id)

    monkeypatch.setattr(fabric_scans, "cutting_department_scope", lambda *_args: "CUT")
    monkeypatch.setattr(fabric_scans, "now_utc", lambda: scan_time)
    statements = []
    with TestSessionLocal() as db:
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "FROM FABRIC_SCANS" in statement.upper():
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = fabric_scans.scan(
                fabric_scans.ScanInput(code="B123-R4", direction="received"),
                db,
                SimpleNamespace(id=9, name="Cutting operator"),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result == {
        "duplicate": True,
        "row": {
            "id": existing_id,
            "report_date": date(2026, 9, 22),
            "direction": "received",
            "fabric_name": "Cotton jersey",
            "batch_no": "BATCH-123",
            "color": "navy",
            "roll_number": 4,
            "operator_name": "Cutting operator",
            "scanned_at": scan_time,
        },
    }
    assert len(statements) == 1
    selected_columns = statements[0].split(" from fabric_scans", 1)[0]
    assert "fabric_scans.id" in selected_columns
    assert "fabric_scans.operator_name" in selected_columns
    assert "fabric_scans.batch_id" not in selected_columns
    assert "fabric_scans.operator_id" not in selected_columns
    assert "fabric_scans.department" not in selected_columns
