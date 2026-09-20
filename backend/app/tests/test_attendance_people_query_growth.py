"""People snapshots batch reference reads while preserving device isolation."""
from math import ceil

import pytest
from sqlalchemy import event

from app.models import AttendancePerson
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_attendance import INTEGRATION_HEADERS, person, snapshot


def _import(client, payload):
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        result = client.post("/api/attendance/integration/people", headers=INTEGRATION_HEADERS, json=payload)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("count", [1, 10, 50, 401])
def test_people_import_reads_are_chunked_for_create_and_update(client, count):
    people = [person(str(index), f"Synthetic person {index}") for index in range(count)]
    for attempt in range(2):
        response, statements = _import(client, snapshot(*people))
        assert response.status_code == 200, response.text
        assert response.json()["created"] == (count if attempt == 0 else 0)
        assert response.json()["updated"] == (count if attempt else 0)
        reads = [sql for sql in statements if "FROM attendance_people" in sql]
        print(f"People {count}, attempt {attempt}: {len(statements)} SELECTs, {len(reads)} people reads")
        assert len(reads) == ceil(count / 400)
        for row in people:
            row["full_name"] += " updated"
    with TestSessionLocal() as db:
        rows = db.query(AttendancePerson).all()
        assert len(rows) == count
        assert all(row.full_name.endswith(" updated") and row.present_on_device for row in rows)


def test_people_snapshot_keeps_device_scope_and_rejects_duplicates_atomically(client):
    first, _ = _import(client, snapshot(person("1", "Device one"), person("2", "Absent later")))
    second, _ = _import(client, snapshot(person("1", "Device two"), device_key="other-device"))
    assert first.status_code == second.status_code == 200
    duplicate, _ = _import(client, snapshot(person("1", "Bad overwrite"), person("1", "Duplicate")))
    assert duplicate.status_code == 400
    with TestSessionLocal() as db:
        assert {row.full_name for row in db.query(AttendancePerson).all()} == {"Device one", "Device two", "Absent later"}
    partial = snapshot(person("1", "Changed one"))
    partial["full_snapshot"] = False
    assert _import(client, partial)[0].json()["marked_absent"] == 0
    full, _ = _import(client, snapshot(person("1", "Changed one")))
    assert full.status_code == 200
    assert full.json()["marked_absent"] == 1
    with TestSessionLocal() as db:
        other = db.query(AttendancePerson).filter_by(device_id=second.json()["device_id"]).one()
        assert other.full_name == "Device two" and other.present_on_device
