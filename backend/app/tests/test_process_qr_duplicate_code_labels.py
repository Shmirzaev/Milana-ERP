from uuid import uuid4


def test_manual_order_shared_operation_codes_issue_all_labels_and_clean_up(client, auth_headers):
    order_no = f"MAN-DUMMY-{uuid4().hex[:12].upper()}"
    size = "46"
    label_rows = [
        {
            "label_uid": (
                f"PY:MAN:999:DUMMY-KROY:{'SEW-NEW' if index == 0 else f'SEW-NEW-{index + 1}'}:MIL:SEW-01:{size}:1"
            ),
            "payload": f"MW2*DUMMY*{index + 1}",
            "production_no": order_no,
            "batch_no": "DUMMY-KROY",
            "model_code": "DUMMY-MODEL",
            "operation_section": "sewing",
            "operation_code": "SEW-NEW",
            "operation_name": f"Dummy checked process {index + 1}",
            "sewing_line_code": "SEW-01",
            "sewing_line_name": "Dummy sewing line",
            "cutting_passport_no": "DUMMY-KROY",
            "size": size,
            "copy_index": 1,
            "quantity": 68,
            "rate_per_piece": 290 + index,
            "currency": "UZS",
        }
        for index in range(20)
    ]

    issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={"labels": label_rows},
        headers=auth_headers,
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["created_count"] == 20
    assert issued.json()["existing_count"] == 0

    listed = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 5000},
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 20
    assert {row["operation_code"] for row in listed.json()["items"]} == {"SEW-NEW"}

    deleted = client.post(
        "/api/payroll/qr-labels/delete-batch",
        json={"size": size, "label_ids": [row["id"] for row in listed.json()["items"]]},
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted_count": 20, "size": size}

    cleaned = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 5000},
        headers=auth_headers,
    )
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["total"] == 0
