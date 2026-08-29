from uuid import uuid4


def _employee_payload(employee_no: str, name: str) -> dict:
    return {
        "employee_no": employee_no,
        "full_name": name,
        "position": "Operator",
        "status": "active",
    }


def test_employee_number_can_be_created_and_edited(client, auth_headers):
    suffix = str(uuid4().int)[:12]
    first_no = f"7{suffix}"
    second_no = f"8{suffix}"
    edited_no = f"9{suffix}"

    first = client.post(
        "/api/employees",
        json=_employee_payload(first_no, "Employee Number First"),
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["employee_no"] == first_no

    second = client.post(
        "/api/employees",
        json=_employee_payload(second_no, "Employee Number Second"),
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text

    duplicate = client.patch(
        f"/api/employees/{second.json()['id']}",
        json={"employee_no": first_no},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "Employee number already exists in this factory"

    edited = client.patch(
        f"/api/employees/{first.json()['id']}",
        json={"employee_no": f"  {edited_no}  "},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["employee_no"] == edited_no

    listed = client.get("/api/employees", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_first = next(row for row in listed.json() if row["id"] == first.json()["id"])
    assert listed_first["employee_no"] == edited_no


def test_employee_number_rejects_non_numeric_values_and_can_be_cleared(client, auth_headers):
    employee_no = f"6{str(uuid4().int)[:12]}"
    created = client.post(
        "/api/employees",
        json=_employee_payload(employee_no, "Employee Number Validation"),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    invalid = client.patch(
        f"/api/employees/{created.json()['id']}",
        json={"employee_no": "EMP-123"},
        headers=auth_headers,
    )
    assert invalid.status_code == 422, invalid.text

    cleared = client.patch(
        f"/api/employees/{created.json()['id']}",
        json={"employee_no": ""},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["employee_no"] is None
