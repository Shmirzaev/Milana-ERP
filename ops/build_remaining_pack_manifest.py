from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any


SOURCE_WORKBOOK_SHA256 = "42d76811d50e0a4839ba1adf520863d6514d332500d5519f625a88850f89bbe6"
STANDARD_QR_RE = re.compile(r"^(?:uzerp_ii_(\d+)_(\d+)|(\d{7}))$", re.IGNORECASE)


def clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalized_base(value: Any) -> str:
    return re.sub(r"[^A-Z0-9А-Я]", "", clean(value).upper())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^(?:VARIANT|VAR|V)[\s_-]*", "", clean(value).upper(), count=1)
    key = re.sub(r"[^A-Z0-9А-Я]", "", value)
    return str(int(key)) if key.isdigit() else key


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_identifiers(row: dict[str, Any]) -> tuple[str, str, str, str | None]:
    record = int(row["record"])
    photo_hash = clean(row["photo_sha256"]).casefold()
    qr = clean(row.get("qr_code")).casefold() or None
    record_key = f"completed-workbook-record-{record}-{photo_hash[:16]}"
    if qr:
        barcode = qr
        match = STANDARD_QR_RE.fullmatch(qr)
        if match and match.group(1) and match.group(2):
            package_no = f"OLD-{match.group(1)}-{match.group(2)}"
        elif match:
            package_no = f"OLD-{match.group(3)}"
        else:
            package_no = f"OLD-QR-{hashlib.sha256(qr.encode('utf-8')).hexdigest()[:16].upper()}"
    else:
        token = f"{record:04d}-{photo_hash[:16].upper()}"
        barcode = f"NOQR-{token}"
        package_no = f"OLD-NOQR-{token}"
    if len(barcode) > 64 or len(package_no) > 64:
        raise ValueError(f"Record {record}: generated identifier is too long")
    return record_key, barcode, package_no, qr


def build(args: argparse.Namespace) -> dict[str, Any]:
    if file_sha256(args.source_workbook) != SOURCE_WORKBOOK_SHA256:
        raise ValueError("Source workbook hash changed")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    output_rows: list[dict[str, Any]] = []
    args.output_photos.mkdir(parents=True, exist_ok=True)
    for source in payload["rows"]:
        if source["action"] != "import":
            continue
        source_photo = args.input_photos / source["photo_file"]
        if file_sha256(source_photo) != clean(source["photo_sha256"]).casefold():
            raise ValueError(f"Record {source['record']}: photo evidence changed")
        target_photo = args.output_photos / source["photo_file"]
        shutil.copy2(source_photo, target_photo)
        record_key, barcode, package_no, qr = package_identifiers(source)
        sizes = [clean(value) for value in clean(source.get("sizes_text")).split(",") if clean(value)]
        model_number = clean(source.get("model_number"))
        article = clean(source.get("article"))
        row = {
            "record_key": record_key,
            "qr_code": qr,
            "has_source_qr": qr is not None,
            "package_barcode": barcode,
            "package_no": package_no,
            "model_number": model_number,
            "article": article,
            "sizes": sizes,
            "weight_kg": None if source.get("weight_kg") in (None, "") else str(Decimal(str(source["weight_kg"]))),
            "quantity": int(source["quantity"]),
            "quantity_defaulted": source.get("quantity_defaulted") is True,
            "color": "Not specified",
            "source_photo": source["photo_file"],
            "source_photo_sha256": source["photo_sha256"],
            "source_reference": f"Completed workbook row {source['excel_row']}: {source['source_file']}",
            "source_workbook": args.source_workbook.name,
            "source_workbook_sha256": SOURCE_WORKBOOK_SHA256,
            "review_status": "approved",
            "review_basis": "User approved missing QR, default quantity 60, and matching duplicate rules on 2026-09-03",
            "allowed_blank_weight": source.get("weight_kg") in (None, ""),
            "allowed_blank_sizes": not sizes,
            "target_kind": source["target_kind"],
            "original_model_number": model_number,
            "original_article": article,
            "workbook_record_number": int(source["record"]),
            "workbook_excel_row": int(source["excel_row"]),
        }
        output_rows.append(row)

    if len(output_rows) != 543:
        raise ValueError(f"Expected 543 import rows, found {len(output_rows)}")
    keys = [row["record_key"] for row in output_rows]
    barcodes = [row["package_barcode"] for row in output_rows]
    package_nos = [row["package_no"] for row in output_rows]
    qrs = [row["qr_code"] for row in output_rows if row["has_source_qr"]]
    if len(keys) != len(set(keys)) or len(barcodes) != len(set(barcodes)) or len(package_nos) != len(set(package_nos)):
        raise ValueError("Generated package identifiers are not unique")
    if len(qrs) != len(set(qrs)):
        raise ValueError("Selected rows still repeat a source QR")

    manifest = {
        "version": 3,
        "source": "User-approved remaining old-ERP sticker rules",
        "source_workbook_sha256": SOURCE_WORKBOOK_SHA256,
        "expected_rows": len(output_rows),
        "expected_quantity": sum(row["quantity"] for row in output_rows),
        "expected_known_weight_kg": str(
            sum(
                (Decimal(row["weight_kg"]) for row in output_rows if row["weight_kg"] is not None),
                Decimal("0"),
            )
        ),
        "expected_null_weight_rows": sum(row["weight_kg"] is None for row in output_rows),
        "expected_unique_identities": len(
            {
                (row["target_kind"], normalized_base(row["model_number"]), normalized_variant(row["article"]))
                for row in output_rows
            }
        ),
        "expected_source_qr_rows": sum(row["has_source_qr"] for row in output_rows),
        "expected_no_source_qr_rows": sum(not row["has_source_qr"] for row in output_rows),
        "expected_default_quantity_rows": sum(row["quantity_defaulted"] for row in output_rows),
        "expected_catalog_rows": sum(row["target_kind"] == "catalog" for row in output_rows),
        "expected_hidden_legacy_rows": sum(row["target_kind"] == "hidden_legacy" for row in output_rows),
        "rows": output_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-photos", type=Path, required=True)
    parser.add_argument("--source-workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-photos", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps({key: result[key] for key in result if key != "rows"}, ensure_ascii=False, indent=2))
