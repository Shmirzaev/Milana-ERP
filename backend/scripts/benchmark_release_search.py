"""Deterministic, read-only search benchmark for release gates.

Run inside a release container. The script creates an in-memory JWT for an
existing active super-admin, performs only GET requests, warms every endpoint,
and emits comparable JSON. It never creates or mutates ERP business data.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.parse
import urllib.request

from sqlalchemy import func

from app.core.deps import user_permissions
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Model, StockBatch, User


def request(base_url: str, path: str, headers: dict[str, str]) -> tuple[float, int, int, int]:
    req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
        status = response.status
    elapsed_ms = (time.perf_counter() - started) * 1000
    body = json.loads(raw)
    if isinstance(body, list):
        rows = len(body)
    elif isinstance(body, dict):
        rows = len(body.get("rows") or body.get("items") or [])
    else:
        rows = 0
    return elapsed_ms, status, rows, len(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:10000")
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if args.warmups < 1 or args.samples < 3 or args.rounds < 1:
        raise SystemExit("Require at least one warm-up and three measured samples")

    with SessionLocal() as db:
        user = next(
            row
            for row in db.query(User).filter(User.is_active.is_(True)).all()
            if "*" in user_permissions(row)
        )
        model = (
            db.query(Model.code)
            .filter(Model.catalog_scope == "standard", Model.code.isnot(None))
            .order_by(Model.id.desc())
            .first()
        )
        common_unit = (
            db.query(StockBatch.unit, func.count(StockBatch.id).label("row_count"))
            .filter(StockBatch.archived_at.is_(None), StockBatch.quantity > 0)
            .group_by(StockBatch.unit)
            .order_by(func.count(StockBatch.id).desc())
            .first()
        )
        if not model or not model.code or not common_unit or not common_unit.unit:
            raise RuntimeError("Production benchmark seed terms are unavailable")
        model_term = str(model.code)
        inventory_term = str(common_unit.unit)
        token = create_access_token(user.id, extra={"factory_code": user.factory_code or "MIL"})

    quote = urllib.parse.quote
    endpoints = {
        "global_search": f"/api/search?q={quote(model_term)}",
        "model_options": f"/api/model-options?search={quote(model_term)}&page=1&page_size=30",
        "model_groups": f"/api/models/variant-groups?q={quote(model_term)}&compact=true&include_total=true&page=1&page_size=20",
        "inventory_batches": f"/api/inventory/batches?q={quote(inventory_term)}&include_total=true&page=1&page_size=50",
        "inventory_stock": f"/api/inventory/stock?q={quote(inventory_term)}&include_total=true&page=1&page_size=50",
    }
    headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}
    evidence: dict[str, dict[str, float | int]] = {}
    for name, path in endpoints.items():
        for _ in range(args.warmups):
            request(args.base_url, path, headers)
        samples = [
            request(args.base_url, path, headers)
            for _ in range(args.rounds)
            for _ in range(args.samples)
        ]
        if any(sample[1] != 200 for sample in samples):
            raise RuntimeError(f"{name} did not return HTTP 200 for every sample")
        elapsed = [sample[0] for sample in samples]
        evidence[name] = {
            "median_ms": round(statistics.median(elapsed), 2),
            "p95_ms": round(sorted(elapsed)[max(0, math.ceil(len(elapsed) * 0.95) - 1)], 2),
            "rows": samples[-1][2],
            "response_bytes": samples[-1][3],
        }
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
