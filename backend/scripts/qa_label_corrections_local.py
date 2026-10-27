"""Serve disposable, seeded candidate data; never connects to production."""
import json
import os
from pathlib import Path

if os.environ.get("LABEL_CORRECTION_LOCAL_QA") != "1":
    raise SystemExit("Set LABEL_CORRECTION_LOCAL_QA=1 for disposable local QA")

# The test harness unconditionally creates its own temporary SQLite DB and
# replaces the application's SessionLocal/get_db before any fixture writes.
from app.tests.conftest import TestSessionLocal, test_engine
from app.db.base import Base
from app.db.seed import seed
from app.main import app
from app.models import Customer, CuttingRecord, Department, Employee, ModelImage, ProductionOrder, SalesOrder, WorkOrder
from app.tests.test_package_label_query_growth import _package_case
from app.tests.test_payroll_returned_split_corrections import _returned_group
from app.tests.test_payroll import _create_user_with_permissions
from app.tests.test_production_flow import _VALID_PNG
from app.services.print_response import warehouse_print_response
from fastapi.testclient import TestClient
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

assert test_engine.dialect.name == "sqlite"
Base.metadata.create_all(test_engine)
seed()
client = TestClient(app)
login = client.post("/api/auth/token", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
assert login.status_code == 200
headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
group = _returned_group(client, headers)
employees, original, records, endpoint = (group[key] for key in ("employees", "original", "records", "endpoint"))
scanner_headers = _create_user_with_permissions(client, headers, email="scanner-label-qa@example.com", permissions=["payroll.view", "payroll.scan"])
with TestSessionLocal() as db:
    for row, name in zip(employees, ("QA Alice", "QA Bob", "QA Carol")):
        db.get(Employee, row["id"]).full_name = name
    package_ids, _ = _package_case(db, 6)
    for picture in db.query(ModelImage).filter(ModelImage.file_name.like("PERF12%")):
        picture.file_data = _VALID_PNG
    order = db.query(ProductionOrder).filter(ProductionOrder.production_no.like("PERF12-PO-%")).one()
    customer = Customer(name="QA Client & Textile Factory")
    db.add(customer)
    db.flush()
    sales = SalesOrder(order_no="SO-QA-CLIENT", customer_id=customer.id)
    db.add(sales)
    db.flush()
    order.sales_order_id = sales.id
    work = WorkOrder(production_order_id=order.id, operation="cutting", department_id=db.query(Department).filter_by(code="CUT").one().id)
    db.add(work)
    db.flush()
    cut = CuttingRecord(work_order_id=work.id)
    db.add(cut)
    db.commit()
    manifest = {"split_endpoint": endpoint, "original_record_id": original["id"], "employees": employees,
                "cutting_url": f"/api/cutting/records/{cut.id}/production-sheet",
                "package_url": "/api/packages/label-sheet/by-ids?ids=" + ",".join(map(str, package_ids)),
                "database": str(test_engine.url.database)}
output = Path(os.environ["LABEL_CORRECTION_QA_OUTPUT"])
output.mkdir(parents=True, exist_ok=True)
(output / "manifest.json").write_text(json.dumps(manifest, default=str, indent=2), encoding="utf-8")
for name, url in (("cutting", manifest["cutting_url"]), ("packages", manifest["package_url"])):
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    (output / f"{name}.html").write_text(response.text, encoding="utf-8")
@app.get("/qa-label-artifacts/{name}")
def qa_artifact(name: str):
    assert name in {"cutting.html", "packages.html"}
    return warehouse_print_response((output / name).read_text(encoding="utf-8"))


@app.get("/qa-payroll")
def qa_payroll(actor: str = "admin"):
    assert actor in {"admin", "scanner"}
    response = HTMLResponse((output / "payroll-app.html").read_text(encoding="utf-8"))
    value = headers["Authorization"] if actor == "admin" else scanner_headers["Authorization"]
    response.set_cookie("erp_access_token", value.removeprefix("Bearer "), httponly=True, samesite="lax")
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


app.mount("/qa-assets", StaticFiles(directory=output), name="qa-assets")
print("Disposable QA ready on 127.0.0.1:8107", flush=True)
uvicorn.run(app, host="127.0.0.1", port=8107, log_level="warning")
