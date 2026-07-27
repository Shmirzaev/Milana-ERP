from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from uuid import uuid4

from openpyxl import load_workbook


def _create_report_test_flow(client, headers, capacity: int = 500) -> dict:
    suffix = uuid4().hex[:8].upper()
    created = client.post(
        "/api/sewing-flows",
        json={
            "name": f"Daily Report Test {suffix}",
            "code": f"DR-{suffix}",
            "capacity_per_day": capacity,
            "is_active": True,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_sewing_daily_report_saves_without_mutating_workflow(client, auth_headers):
    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 120,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 120}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    po_id = int(created.json()["id"])
    passport_no = f"KR-DAILY-{po_id}"
    passport = client.post(
        "/api/cutting-passports",
        json={
            "passport_no": passport_no,
            "date": datetime.now(timezone.utc).isoformat(),
            "production_order_id": po_id,
            "has_print": False,
        },
        headers=auth_headers,
    )
    assert passport.status_code == 201, passport.text

    work_orders = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    sewing_wo = next(row for row in work_orders.json() if row["operation"] == "sewing")

    flow = _create_report_test_flow(client, auth_headers)

    assignment = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow["id"],
            "quantity": 120,
            "planned_start": datetime.now(timezone.utc).isoformat(),
            "planned_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers,
    )
    assert assignment.status_code == 201, assignment.text
    assignment_id = int(assignment.json()["id"])

    context = client.get(
        f"/api/sewing-daily-reports/line-context?sewing_flow_id={flow['id']}",
        headers=auth_headers,
    )
    assert context.status_code == 200, context.text
    active = context.json()["active_work_orders"]
    active_row = next(
        row
        for row in active
        if row["work_order_id"] == sewing_wo["id"] and row["sewing_assignment_id"] == assignment_id
    )
    assert active_row["model_id"] == 1
    assert active_row["model_no"]
    assert "variant_no" in active_row
    assert "model_image_url" in active_row
    assert "fabric_image_url" in active_row
    assert active_row["kroy_no"] == passport_no

    report_date = date.today().isoformat()
    saved = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": report_date,
            "sewing_flow_id": flow["id"],
            "work_order_id": sewing_wo["id"],
            "sewing_assignment_id": assignment_id,
            "manual_model_no": "MANUAL-7381",
            "manual_variant_no": "V-4",
            "sewn_qty": 42,
            "defective_qty": 2,
            "defect_reason": "Needle mark",
        },
        headers=auth_headers,
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["line_code"] == flow["code"]
    assert body["sewn_qty"] == 42
    assert body["defective_qty"] == 2
    assert body["manual_model_no"] == "MANUAL-7381"
    assert body["manual_variant_no"] == "V-4"
    assert body["model_no"] == "MANUAL-7381"
    assert body["variant_no"] == "V-4"
    assert body["kroy_no"] == passport_no

    listed = client.get(f"/api/sewing-daily-reports?report_date={report_date}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_body = listed.json()
    assert listed_body["total_sewn_qty"] == 42
    assert listed_body["total_defective_qty"] == 2
    assert listed_body["summary"][0]["line_code"] == flow["code"]
    assert listed_body["summary"][0]["orders"]
    assert listed_body["summary"][0]["models"][0]["model_id"] == 1
    assert listed_body["summary"][0]["models"][0]["model_no"] == "MANUAL-7381"
    assert listed_body["summary"][0]["models"][0]["variant_no"] == "V-4"
    assert listed_body["summary"][0]["kroy_nos"] == [passport_no]
    assert listed_body["rows"][0]["model_id"] == 1
    assert listed_body["rows"][0]["model_no"] == "MANUAL-7381"
    assert listed_body["rows"][0]["variant_no"] == "V-4"
    assert listed_body["rows"][0]["kroy_no"] == passport_no

    unchanged_work_order = client.get(f"/api/work-orders/{sewing_wo['id']}", headers=auth_headers)
    assert unchanged_work_order.status_code == 200, unchanged_work_order.text
    assert unchanged_work_order.json()["passed_qty"] == sewing_wo["passed_qty"]
    assert unchanged_work_order.json()["failed_qty"] == sewing_wo["failed_qty"]

    assignments_after = client.get(f"/api/work-orders/{sewing_wo['id']}/assignments", headers=auth_headers)
    assert assignments_after.status_code == 200, assignments_after.text
    refreshed_assignment = next(row for row in assignments_after.json() if row["id"] == assignment_id)
    assert refreshed_assignment["completed_qty"] == 0
    assert refreshed_assignment["status"] == "planned"


def test_sewing_daily_report_requires_reason_for_defects(client, auth_headers):
    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 20,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 20}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    po_id = int(created.json()["id"])

    work_orders = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    sewing_wo = next(row for row in work_orders.json() if row["operation"] == "sewing")

    flow = _create_report_test_flow(client, auth_headers)
    assigned = client.patch(
        f"/api/work-orders/{sewing_wo['id']}",
        json={"sewing_flow_id": flow["id"]},
        headers=auth_headers,
    )
    assert assigned.status_code == 200, assigned.text

    missing_reason = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": date.today().isoformat(),
            "sewing_flow_id": flow["id"],
            "work_order_id": sewing_wo["id"],
            "sewn_qty": 10,
            "defective_qty": 1,
        },
        headers=auth_headers,
    )
    assert missing_reason.status_code == 422, missing_reason.text


def test_sewing_daily_report_allows_manual_entry_without_order(client, auth_headers):
    flow = _create_report_test_flow(client, auth_headers)
    report_date = date.today().isoformat()

    saved = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": report_date,
            "sewing_flow_id": flow["id"],
            "work_order_id": None,
            "manual_model_no": "MANUAL-2048",
            "manual_variant_no": "V-17",
            "kroy_no": "KR-MANUAL-17",
            "sewn_qty": 36,
            "defective_qty": 1,
            "defect_reason": "Needle mark",
            "notes": "Entered without an attached order",
        },
        headers=auth_headers,
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["work_order_id"] is None
    assert body["sewing_assignment_id"] is None
    assert body["production_order_id"] is None
    assert body["order_no"] is None
    assert body["model_id"] is None
    assert body["model_no"] == "MANUAL-2048"
    assert body["variant_no"] == "V-17"
    assert body["kroy_no"] == "KR-MANUAL-17"
    assert body["sewn_qty"] == 36

    listed = client.get(f"/api/sewing-daily-reports?report_date={report_date}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["rows"] if item["id"] == body["id"])
    assert row["work_order_id"] is None
    assert row["model_no"] == "MANUAL-2048"
    assert row["kroy_no"] == "KR-MANUAL-17"
    summary = next(item for item in listed.json()["summary"] if item["sewing_flow_id"] == flow["id"])
    assert summary["orders"] == []
    assert summary["models"][0]["model_no"] == "MANUAL-2048"
    assert summary["kroy_nos"] == ["KR-MANUAL-17"]

    missing_model = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": report_date,
            "sewing_flow_id": flow["id"],
            "work_order_id": None,
            "sewn_qty": 10,
        },
        headers=auth_headers,
    )
    assert missing_model.status_code == 422, missing_model.text


def test_sewing_daily_report_supports_two_part_dynamic_sections(client, auth_headers):
    flows = client.get("/api/sewing-flows", headers=auth_headers)
    assert flows.status_code == 200, flows.text
    sectioned_flow = next(flow for flow in flows.json() if flow["code"] == "SEW-01")
    report_date = "2099-12-30"

    saved = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": report_date,
            "sewing_flow_id": sectioned_flow["id"],
            "work_order_id": None,
            "manual_model_no": "SET-2048",
            "manual_variant_no": "V-17",
            "section_no": 4,
            "top_qty": 18,
            "bottom_qty": 10,
            "sewn_qty": 28,
            "defective_qty": 0,
        },
        headers=auth_headers,
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["section_no"] == 4
    assert body["top_qty"] == 18
    assert body["bottom_qty"] == 10

    listed = client.get(f"/api/sewing-daily-reports?report_date={report_date}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["rows"] if item["id"] == body["id"])
    assert row["section_no"] == 4
    assert row["top_qty"] == 18
    assert row["bottom_qty"] == 10


def test_sewing_daily_report_exports_saved_rows_for_chosen_dates(client, auth_headers):
    flow = _create_report_test_flow(client, auth_headers)
    report_date = "2099-12-29"
    saved = client.post(
        "/api/sewing-daily-reports",
        json={
            "report_date": report_date,
            "sewing_flow_id": flow["id"],
            "work_order_id": None,
            "manual_model_no": "EXPORT-2048",
            "manual_variant_no": "V-29",
            "kroy_no": "KR-EXPORT-29",
            "sewn_qty": 48,
            "defective_qty": 2,
            "defect_reason": "hole_present",
            "notes": "Export verification row",
        },
        headers=auth_headers,
    )
    assert saved.status_code == 201, saved.text

    excel_response = client.get(
        (
            "/api/sewing-daily-reports/export.xlsx"
            f"?from_date={report_date}&to_date={report_date}&lang=en"
        ),
        headers=auth_headers,
    )
    assert excel_response.status_code == 200, excel_response.text
    assert excel_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert ".xlsx" in excel_response.headers["content-disposition"]
    workbook = load_workbook(BytesIO(excel_response.content), data_only=False)
    assert workbook.sheetnames == ["Summary", "Entries"]
    summary_sheet = workbook["Summary"]
    entries_sheet = workbook["Entries"]
    assert summary_sheet["A1"].value == "Daily Sewing Report"
    assert summary_sheet["A7"].value == f"{flow['name']} ({flow['code']})"
    assert summary_sheet["B7"].value == 48
    assert summary_sheet["C7"].value == 2
    assert str(summary_sheet.cell(summary_sheet.max_row, 2).value).startswith("=SUM(")
    assert entries_sheet["G6"].value == "EXPORT-2048"
    assert entries_sheet["H6"].value == "V-29"
    assert entries_sheet["I6"].value == "KR-EXPORT-29"
    assert entries_sheet["J6"].value == 48
    assert entries_sheet["K6"].value == 2
    assert entries_sheet["L6"].value == "Hole present"
    assert entries_sheet["M6"].value == "Export verification row"

    pdf_response = client.get(
        (
            "/api/sewing-daily-reports/export.pdf"
            f"?from_date={report_date}&to_date={report_date}&lang=en"
        ),
        headers=auth_headers,
    )
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert ".pdf" in pdf_response.headers["content-disposition"]
    assert pdf_response.content.startswith(b"%PDF")
    assert len(pdf_response.content) > 10_000

    invalid_range = client.get(
        "/api/sewing-daily-reports/export.xlsx?from_date=2099-12-30&to_date=2099-12-29",
        headers=auth_headers,
    )
    assert invalid_range.status_code == 400
