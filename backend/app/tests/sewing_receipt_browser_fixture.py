"""Explicit synthetic seed helper for isolated, loopback browser QA only.

Use runpy.run_path to avoid importing pytest's conftest into an application seed
process. Caller supplies an authenticated httpx client; credentials are not logged.
"""
from uuid import uuid4


def seed_sewing_receipt_browser(client, *, model_id=1, report_date="2026-11-07"):
    if client.base_url.host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise ValueError("Synthetic sewing fixtures require a loopback QA application")

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    marker = "QA-SEW-" + uuid4().hex[:8].upper()
    flows = [post("/api/sewing-flows", {"factory_code": "MIL", "code": f"{marker}-{index}",
        "name": f"Manual receipt QA line {index}", "capacity_per_day": 500, "is_active": True}) for index in (1, 2)]
    order = post("/api/planning/create-branded-production", {
        "production_type": "branded_stock", "model_id": model_id, "planned_quantity": 128,
        "batches": [{"name": marker, "planned_quantity": 128}],
        "items": [{"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 128}],
    })
    order = get(f"/api/production-orders/{order['id']}")
    work = {row["operation"]: row["id"] for row in order["work_orders"]}
    batch_id = order["batches"][0]["id"]
    post("/api/cutting/records", {"work_order_id": work["cutting"], "production_batch_id": batch_id,
        "input_quantity": 10, "input_unit": "kg", "cut_pieces": 128, "passed_pieces": 128,
        "defective_pieces": 0, "bundles": [{"color": "white", "size": "M", "quantity": 32, "count": 4, "sewing_factory": "MIL"}]})
    plan = get(f"/api/inventory/accessory-issue-plan?production_order_id={order['id']}")
    rows = [row for row in plan["rows"] if float(row["remaining_quantity"] or 0) > 0]
    if rows:
        warehouse = next(row for row in get("/api/inventory/warehouses") if row["type"] == "accessory_storage")
        for row in rows:
            shortage = max(0, float(row["remaining_quantity"] or 0) - float(row["available_quantity"] or 0))
            if shortage:
                post("/api/inventory/receive", {"item_id": row["item_id"], "batch_no": f"{marker}-{row['item_id']}",
                    "quantity": shortage + 1, "unit": row["unit"], "cost_per_unit": 1,
                    "warehouse_id": warehouse["id"], "qc_status": "passed"})
        post("/api/inventory/accessory-issues", {"production_order_id": order["id"],
            "lines": [{"item_id": row["item_id"], "quantity": row["remaining_quantity"], "unit": row["unit"]} for row in rows]})
    section_flow = next(flow for flow in get("/api/sewing-flows?factory_code=MIL") if flow["code"] == "SEW-01")
    reports = [post("/api/sewing-daily-reports", {"report_date": report_date, "sewing_flow_id": section_flow["id"],
        "manual_model_no": marker, "manual_variant_no": "TOP" if top else "BOTTOM",
        "section_no": index, "top_qty": top, "bottom_qty": bottom, "sewn_qty": top + bottom})
        for index, (top, bottom) in enumerate(((24, 0), (0, 16)), 1)]
    return {"marker": marker, "order_id": order["id"], "production_no": order["production_no"],
        "batch_id": batch_id, "work_orders": work, "flow_ids": [flow["id"] for flow in flows],
        "report_ids": [row["id"] for row in reports], "report_date": report_date,
        "scan_route": "/bundles/scan/sewing?factory=MIL", "report_route": "/sewing/daily-report",
        "export_route": f"/api/sewing-daily-reports/export.xlsx?report_date={report_date}&lang=en",
        "expected": {"bundles": 4, "receipt_quantity": 128, "line_assignment_quantity": 128,
                     "excel_parts": [[24, "Top", 24, 0], [16, "Bottom", 0, 16]]}}
