from datetime import datetime, timezone
from unittest.mock import Mock

from app.schemas.inventory.stocktake import add_scan_row, record_first_scan


def test_scan_persistence_uses_caller_session_and_flushes_evidence():
    db = Mock()
    snapshot = {"quantity": 4}
    row = add_scan_row(
        db, stocktake_id=3, identity="package:9", package_id=9,
        category="unexpected", snapshot=snapshot,
    )
    db.add.assert_called_once_with(row)
    assert row.expected is False and row.snapshot == snapshot
    db.flush.assert_not_called()

    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evidence = {"quantity": 4, "items": [{"size": "M", "quantity": 4}]}
    record_first_scan(db, row, snapshot=evidence, code="label", scanned_at=timestamp, scanned_by=7)
    assert (row.scan_snapshot, row.scan_code, row.scanned_at, row.scanned_by) == (
        evidence, "label", timestamp, 7,
    )
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()
