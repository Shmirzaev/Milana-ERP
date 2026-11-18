"""Fixed read-only probe, piped to the verified baseline backend's Python."""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request


ENDPOINTS = (
    ("sales", "/api/sales-orders", True),
    ("production", "/api/production-orders", True),
    ("material_batches", "/api/inventory/batches", True),
    ("packages", "/api/packages", True),
    ("cutting", "/api/cutting-passports", False),
    ("work_orders", "/api/work-orders", False),
    ("shipments", "/api/shipments", False),
)
MAX_BYTES = 32 * 1024 * 1024
STAGE = "initialization"
MEASUREMENTS = {}
CLIENT = None


class ProbeRefusal(ValueError):
    """Only fixed, non-sensitive refusal reasons may leave the probe."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get(base, path, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(base + path, headers=headers)
    start = time.monotonic()
    if CLIENT is not None:
        response = CLIENT.get(path, headers=headers)
        if response.status_code != 200:
            raise urllib.error.HTTPError(path, response.status_code, "Read-only request refused", None, None)
        if len(response.content) > MAX_BYTES:
            raise ProbeRefusal("Read-only probe response exceeded its contract")
        return response.json(), (time.monotonic() - start) * 1000, len(response.content)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(body) > MAX_BYTES:
            raise ProbeRefusal("Read-only probe response exceeded its contract")
    return json.loads(body), (time.monotonic() - start) * 1000, len(body)


def full_read(base, path, paged, token):
    count, seen = 0, set()
    facts = hashlib.sha256()
    expected_total = None
    for page in range(1, 501):
        query = f"?page={page}&page_size=500&include_total=true" if paged else ""
        body, _, _ = get(base, path + query, token)
        if not paged:
            if not isinstance(body, list):
                raise ProbeRefusal("Unexpected complete-list response")
            for row in body:
                facts.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            return {"rows": len(body), "ordered_facts_sha256": facts.hexdigest()}
        if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
            raise ProbeRefusal("Expected explicit paginated response")
        if type(body.get("total")) is not int or body["total"] < 0:
            raise ProbeRefusal("Missing authoritative total")
        if expected_total is None:
            expected_total = body["total"]
        if body["total"] != expected_total:
            raise ProbeRefusal("Business data changed during paginated QA")
        part = body["rows"]
        page_hash = digest(part)
        if part and page_hash in seen:
            raise ProbeRefusal("Endpoint repeated a page")
        seen.add(page_hash)
        for row in part:
            facts.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        count += len(part)
        if count == expected_total:
            return {"rows": count, "ordered_facts_sha256": facts.hexdigest()}
        if not part or count > expected_total:
            raise ProbeRefusal("Incomplete or inconsistent pagination")
    raise ProbeRefusal("Read-only QA page bound exceeded")


def performance(before, after, *, median_budget=.10, p95_budget=.15):
    global MEASUREMENTS
    median_before = statistics.median(before)
    median_after = statistics.median(after)
    p95_before = sorted(before)[math.ceil(len(before) * .95) - 1]
    p95_after = sorted(after)[math.ceil(len(after) * .95) - 1]
    MEASUREMENTS = {"samples_per_slot": len(before), "baseline_median_ms": round(median_before, 2),
                    "candidate_median_ms": round(median_after, 2),
                    "baseline_p95_ms": round(p95_before, 2), "candidate_p95_ms": round(p95_after, 2)}
    if median_after > median_before * (1 + median_budget):
        raise ProbeRefusal("Read-only API median performance budget failed")
    if p95_after > p95_before * (1 + p95_budget):
        raise ProbeRefusal("Read-only API p95 performance budget failed")
    return MEASUREMENTS


@contextlib.contextmanager
def readonly_session(snapshot=None):
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.db.session import engine
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if snapshot is not None:
                import re
                if not re.fullmatch(r"[0-9A-F]+-[0-9A-F]+-[0-9]+", snapshot):
                    raise ProbeRefusal("Invalid read-only snapshot identity")
                connection.exec_driver_sql("SET TRANSACTION SNAPSHOT '" + snapshot + "'")
            with Session(bind=connection) as session:
                yield session


def complete_cutting(snapshot, user_id, token):
    # The UI list caps at 500; enumerate authoritative scoped IDs on the same
    # snapshot, then exercise the real detail route for every matching passport.
    from app.api.routes.cutting_passports import _filtered_passports
    from app.schemas import CuttingPassport, User
    from app.models.factory_scope_service import bind_session_factory
    with readonly_session(snapshot) as db:
        user = db.get(User, user_id)
        bind_session_factory(user, None)
        ids = _filtered_passports(db, user, None, None, None, None, None).with_entities(CuttingPassport.id).all()
        ids = sorted({row[0] for row in ids})
    if len(ids) > 10000:
        raise ProbeRefusal("Cutting detail probe bound exceeded")
    facts = hashlib.sha256()
    for passport_id in ids:
        row, _, _ = get("http://127.0.0.1", f"/api/cutting-passports/{passport_id}", token)
        if row.get("id") != passport_id:
            raise ProbeRefusal("Cutting detail identity differs from authoritative scope")
        facts.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return {"rows": len(ids), "ordered_facts_sha256": facts.hexdigest(), "scope": "current_reader_factory_and_department"}


def main():
    global STAGE, CLIENT
    request = json.loads(sys.argv[1])
    from sqlalchemy import text
    from app.schemas import User
    from app.core.deps import user_permissions
    from app.core.security import create_access_token
    STAGE = "database_reader_and_capacity"
    snapshot = request.get("snapshot")
    if request.get("mode") == "facts" and snapshot is None:
        raise ProbeRefusal("Complete facts require one exported read-only snapshot")
    with readonly_session(snapshot) as db:
        users = db.query(User).filter(User.is_active.is_(True)).order_by(User.id).all()
        admin = next((u for u in users if "*" in user_permissions(u)), None)
        if admin is None:
            raise ProbeRefusal("No existing authorized QA reader")
        token = create_access_token(admin.id, {"exp": int(time.time()) + 600})
        user_id = admin.id
        capacity = db.execute(text("SELECT count(*) FROM pg_stat_activity")).scalar_one()
        maximum = int(db.execute(text("SHOW max_connections")).scalar_one())
        invalid = db.execute(text("SELECT count(*) FROM pg_index WHERE NOT indisvalid")).scalar_one()
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if capacity >= maximum * .8 or invalid or revision != [request["database_revision"]]:
            raise ProbeRefusal("Database capacity/index/revision gate failed")
    result = {"database": {"connections": capacity, "max_connections": maximum,
                           "invalid_indexes": invalid, "revision": revision}, "workflows": {}}
    if request.get("mode") == "facts":
        from fastapi import Depends
        from fastapi.testclient import TestClient
        from sqlalchemy.exc import DBAPIError
        from app.main import app
        from app.db.session import get_db
        def frozen_db():
            with readonly_session(snapshot) as session:
                yield session
        app.dependency_overrides[get_db] = frozen_db
        def refuse_write(db=Depends(get_db)):
            try:
                # Even a broken override cannot affect a business row here.
                db.execute(text("UPDATE users SET id=id WHERE false"))
            except DBAPIError as error:
                if getattr(error.orig, "pgcode", None) == "25006":
                    return {"sqlstate": "25006", "write_refused": True}
                raise
            raise ProbeRefusal("API dependency did not enforce a read-only transaction")
        app.add_api_route("/__qa_readonly_refusal", refuse_write, methods=["GET"])
        CLIENT = TestClient(app)
        try:
            STAGE = "frozen_dependency_write_refusal"
            if get("http://127.0.0.1", "/__qa_readonly_refusal")[0] != {"sqlstate": "25006", "write_refused": True}:
                raise ProbeRefusal("API read-only fault challenge failed")
            for name, path, paged in ENDPOINTS:
                STAGE = name + ":frozen_complete_ordered_facts"
                result["workflows"][name] = (complete_cutting(snapshot, user_id, token) if name == "cutting" else
                                             full_read("http://127.0.0.1", path, paged, token))
        finally:
            CLIENT.close()
            app.dependency_overrides.pop(get_db, None)
        print(json.dumps({"revision": revision, "readonly_sqlstate": "25006", "workflows": result["workflows"]}))
        return
    baseline, candidate = request["baseline"], request["candidate"]
    STAGE = "signed_identity_and_anonymous_denial"
    for base in {baseline, candidate}:
        get(base, "/api/auth/me", token)
        try:
            get(base, "/api/production-orders")
        except urllib.error.HTTPError as error:
            if error.code not in {401, 403}:
                raise
        else:
            raise ProbeRefusal("Anonymous production access was accepted")
    for name, path, paged in ENDPOINTS:
        if not paged or name == "packages":
            continue  # Complete facts are checked separately on one frozen snapshot.
        before_times, after_times = [], []
        STAGE = name + ":performance"
        query = "?page=1&page_size=100&include_total=true" if paged else ""
        get(baseline, path + query, token)
        get(candidate, path + query, token)
        for index in range(21):
            if index % 2:
                second, elapsed_after, size_after = get(candidate, path + query, token)
                first, elapsed, size = get(baseline, path + query, token)
            else:
                first, elapsed, size = get(baseline, path + query, token)
                second, elapsed_after, size_after = get(candidate, path + query, token)
            if size_after > size * 1.15:
                raise ProbeRefusal("Workflow benchmark payload budget failed")
            before_times.append(elapsed)
            after_times.append(elapsed_after)
        result["workflows"][name] = performance(before_times, after_times)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"failed": type(error).__name__, "stage": STAGE,
                          "reason": str(error) if isinstance(error, ProbeRefusal) else None,
                          "last_performance": MEASUREMENTS}), file=sys.stderr)
        raise SystemExit(1) from None
