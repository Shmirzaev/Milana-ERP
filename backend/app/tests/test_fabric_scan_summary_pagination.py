from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models.fabric_scan import FabricScan
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_summary_groups(count: int) -> tuple[date, str]:
    day = date(2098, 10, 1)
    marker = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        db.add_all([
            FabricScan(
                department="CUT",
                report_date=day,
                batch_id=1_500_000_000 + index,
                roll_number=1,
                direction="received" if index % 2 == 0 else "returned",
                fabric_name=f"Fabric {marker} {index:04d}",
                batch_no=f"BATCH-{marker}-{index:04d}",
                color=f"Color {index:04d}",
                operator_id=1,
                operator_name="Summary pagination test",
                scanned_at=datetime(2098, 10, 1, tzinfo=timezone.utc),
            )
            for index in range(count)
        ])
        db.commit()
    return day, marker


def test_fabric_scan_summary_opt_in_page_is_sql_bounded_and_legacy_stays_full(client, auth_headers):
    day, marker = _seed_summary_groups(50)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        legacy_response = client.get(
            "/api/fabric-scans",
            params={"report_date": day.isoformat(), "page_size": 1},
            headers=auth_headers,
        )
        page_response = client.get(
            "/api/fabric-scans",
            params={
                "report_date": day.isoformat(),
                "page_size": 1,
                "summary_page": 2,
                "summary_page_size": 10,
            },
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert legacy_response.status_code == 200, legacy_response.text
    assert page_response.status_code == 200, page_response.text
    legacy = legacy_response.json()
    paged = page_response.json()
    assert len(legacy["summary"]) == 50
    assert "summary_pagination" not in legacy
    assert [row["batch_no"] for row in legacy["summary"]] == [
        f"BATCH-{marker}-{index:04d}" for index in range(50)
    ]
    assert len(paged["summary"]) == 10
    assert paged["summary"][0]["batch_no"] == f"BATCH-{marker}-0010"
    assert paged["summary_pagination"] == {
        "page": 2,
        "page_size": 10,
        "total": 50,
        "pages": 5,
    }
    assert len(paged["rows"]) == 1
    assert paged["total"] == 50

    group_reads = [
        statement
        for statement in statements
        if "from fabric_scans" in statement and "group by fabric_scans.batch_id" in statement
    ]
    assert len(group_reads) == 3
    assert " limit ? offset ?" not in group_reads[0]
    assert sum(" limit ? offset ?" in statement for statement in group_reads) == 1
    row_reads = [
        statement
        for statement in statements
        if "from fabric_scans" in statement
        and " limit ? offset ?" in statement
        and "group by" not in statement
    ]
    assert len(row_reads) == 2
    selected_columns = row_reads[-1].split(" from ", 1)[0]
    assert "fabric_scans.operator_name" in selected_columns
    assert "fabric_scans.operator_id" not in selected_columns
    assert "fabric_scans.department" not in selected_columns
    assert "fabric_scans.batch_id" not in selected_columns
