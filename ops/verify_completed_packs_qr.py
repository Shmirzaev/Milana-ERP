from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.security import create_access_token


ROOT = Path("/tmp/completed-packs-production")
payload = json.loads((ROOT / "production-pack-manifest.json").read_text(encoding="utf-8"))
rows = payload["rows"]
token = create_access_token(1, extra={"factory_code": "MIL"})
headers = {"Authorization": f"Bearer {token}"}

internal_package_ids: set[int] = set()
for row in rows:
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

sample_indices = [0, len(rows) // 4, len(rows) // 2, (len(rows) * 3) // 4, len(rows) - 1]
blank_weight_index = next(index for index, row in enumerate(rows) if row.get("weight_kg") is None)
numeric_index = next(index for index, row in enumerate(rows) if str(row["qr_code"]).isdigit())
sample_qrs = [rows[index]["qr_code"] for index in dict.fromkeys(sample_indices + [blank_weight_index, numeric_index])]
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

if len(internal_package_ids) != len(rows):
    raise RuntimeError("QR lookups did not resolve to one distinct package per manifest row")
print(json.dumps({
    "internal_qr_checks": len(rows),
    "unique_internal_package_ids": len(internal_package_ids),
    "public_samples": public_results,
}, ensure_ascii=False, sort_keys=True))
