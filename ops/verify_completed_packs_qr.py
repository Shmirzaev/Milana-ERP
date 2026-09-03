from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Package, PackageBarcodeAlias


ROOT = Path("/tmp/completed-packs-production")
payload = json.loads((ROOT / "production-pack-manifest.json").read_text(encoding="utf-8"))
rows = payload["rows"]
token = create_access_token(1, extra={"factory_code": "MIL"})
headers = {"Authorization": f"Bearer {token}"}

qrs = [row["qr_code"] for row in rows]
with SessionLocal() as db:
    packages = db.query(Package).filter(Package.barcode.in_(qrs)).all()
    aliases = db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.code.in_(qrs)).all()
    db.rollback()
if len(packages) != len(rows) or len(aliases) != len(rows):
    raise RuntimeError(f"Database QR evidence mismatch: packages={len(packages)}, aliases={len(aliases)}")
if len({package.id for package in packages}) != len(rows) or len({alias.package_id for alias in aliases}) != len(rows):
    raise RuntimeError("Database QR evidence does not resolve to distinct packages")

sample_indices = [round(index * (len(rows) - 1) / 19) for index in range(20)]
blank_weight_index = next(index for index, row in enumerate(rows) if row.get("weight_kg") is None)
numeric_index = next(index for index, row in enumerate(rows) if str(row["qr_code"]).isdigit())
internal_indices = list(dict.fromkeys(sample_indices + [blank_weight_index, numeric_index]))
internal_package_ids: set[int] = set()
for index in internal_indices:
    row = rows[index]
    qr = row["qr_code"]
    response = httpx.get(
        f"http://127.0.0.1:10000/api/packages/barcode/{quote(qr, safe='')}",
        headers=headers,
        timeout=30,
        follow_redirects=False,
    )
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or str(body.get("barcode", "")).casefold() != qr.casefold():
        raise RuntimeError(f"Internal QR lookup failed for {qr}: HTTP {response.status_code}")
    if int(body.get("total_quantity") or 0) != int(row["quantity"]):
        raise RuntimeError(f"Internal QR lookup returned the wrong quantity for {qr}")
    internal_package_ids.add(int(body["id"]))

sample_qrs = [rows[index]["qr_code"] for index in dict.fromkeys([0, len(rows) // 4, len(rows) // 2, (len(rows) * 3) // 4, len(rows) - 1, blank_weight_index, numeric_index])]
public_results = []
for qr in sample_qrs:
    response = httpx.get(
        f"https://erp.milanapremium.uz/api/packages/barcode/{quote(qr, safe='')}",
        headers=headers,
        timeout=30,
        follow_redirects=False,
    )
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or str(body.get("barcode", "")).casefold() != qr.casefold():
        raise RuntimeError(f"Public QR lookup failed for {qr}: HTTP {response.status_code}")
    public_results.append({"qr": qr, "package_id": body.get("id"), "http": response.status_code})

if len(internal_package_ids) != len(internal_indices):
    raise RuntimeError("HTTP QR samples did not resolve to distinct packages")
print(json.dumps({
    "database_qr_checks": len(rows),
    "database_alias_checks": len(rows),
    "internal_qr_checks": len(internal_indices),
    "unique_internal_package_ids": len(internal_package_ids),
    "public_samples": public_results,
}, ensure_ascii=False, sort_keys=True))
