from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an ERP catalog manifest from artifact-tool sheet values and XLSX media.")
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--values-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--header-row", type=int, default=2)
    parser.add_argument("--model-column", type=int, default=5)
    parser.add_argument("--fabric-column", type=int, default=6)
    parser.add_argument("--variant-column", type=int, default=7)
    parser.add_argument("--size-column", type=int, default=9)
    parser.add_argument("--model-image-column", type=int, default=4)
    parser.add_argument("--fabric-image-column", type=int, default=8)
    return parser.parse_args()


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).strip().split())


def normalize_model_no(value: object) -> str:
    """Remove accidental spacing around code separators without changing the code alphabet."""
    text = clean(value)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return re.sub(r"\s*-\s*", "-", text)


def normalize_variant_no(value: object) -> str:
    text = clean(value)
    return str(int(text)) if text.isdigit() else text


def safe_cell(row: list, one_based_column: int) -> object:
    index = one_based_column - 1
    return row[index] if 0 <= index < len(row) else None


def drawing_relationships(archive: zipfile.ZipFile, drawing_path: str) -> dict[str, str]:
    parent = posixpath.dirname(drawing_path)
    rels_path = posixpath.join(parent, "_rels", f"{posixpath.basename(drawing_path)}.rels")
    root = ET.fromstring(archive.read(rels_path))
    result: dict[str, str] = {}
    for rel in root.findall("pr:Relationship", NS):
        rel_id = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rel_id and target:
            result[rel_id] = posixpath.normpath(posixpath.join(parent, target))
    return result


def extract_anchored_images(workbook: Path, media_dir: Path) -> list[dict]:
    anchors: list[dict] = []
    with zipfile.ZipFile(workbook) as archive:
        drawing_paths = sorted(
            name for name in archive.namelist()
            if re.fullmatch(r"xl/drawings/drawing\d+\.xml", name)
        )
        for drawing_path in drawing_paths:
            rels = drawing_relationships(archive, drawing_path)
            root = ET.fromstring(archive.read(drawing_path))
            for anchor in list(root):
                origin = anchor.find("xdr:from", NS)
                blip = anchor.find(".//a:blip", NS)
                if origin is None or blip is None:
                    continue
                row_node = origin.find("xdr:row", NS)
                col_node = origin.find("xdr:col", NS)
                rel_id = blip.attrib.get(f"{{{NS['r']}}}embed", "")
                media_path = rels.get(rel_id, "")
                if row_node is None or col_node is None or not media_path or media_path not in archive.namelist():
                    continue
                content = archive.read(media_path)
                sha256 = hashlib.sha256(content).hexdigest()
                suffix = Path(media_path).suffix.lower() or ".png"
                name = f"image_{sha256[:20]}{suffix}"
                target = media_dir / name
                media_dir.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(content)
                anchors.append(
                    {
                        "row": int(row_node.text or 0) + 1,
                        "column": int(col_node.text or 0) + 1,
                        "name": name,
                        "sha256": sha256,
                    }
                )
    return anchors


def unique_images(images: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for image in images:
        sha256 = clean(image.get("sha256"))
        if not sha256 or sha256 in seen:
            continue
        seen.add(sha256)
        result.append({"name": clean(image.get("name")), "sha256": sha256})
    return result


def main() -> None:
    args = parse_args()
    rows = json.loads(args.values_json.read_text(encoding="utf-8"))
    media_dir = args.output_dir / "media"
    anchors = extract_anchored_images(args.workbook, media_dir)

    identity_rows: list[int] = []
    for excel_row in range(args.header_row + 1, len(rows) + 1):
        row = rows[excel_row - 1]
        if clean(safe_cell(row, args.model_column)) and clean(safe_cell(row, args.variant_column)):
            identity_rows.append(excel_row)

    raw_records: list[dict] = []
    for index, excel_row in enumerate(identity_rows):
        next_row = identity_rows[index + 1] if index + 1 < len(identity_rows) else len(rows) + 1
        block_end = next_row - 1
        block = rows[excel_row - 1:block_end]
        model_no = normalize_model_no(safe_cell(rows[excel_row - 1], args.model_column))
        variant_no = normalize_variant_no(safe_cell(rows[excel_row - 1], args.variant_column))
        fabrics = [clean(safe_cell(row, args.fabric_column)) for row in block]
        fabrics = [value for value in fabrics if value]
        sizes = [clean(safe_cell(row, args.size_column)) for row in block]
        sizes = [value for value in sizes if value]
        block_anchors = [image for image in anchors if excel_row <= image["row"] <= block_end]
        model_images = unique_images([image for image in block_anchors if image["column"] == args.model_image_column])
        fabric_images = unique_images([image for image in block_anchors if image["column"] == args.fabric_image_column])
        raw_records.append(
            {
                "modelNo": model_no,
                "variantNo": variant_no,
                "code": f"{model_no}-{variant_no}",
                "name": "",
                "fabric": Counter(fabrics).most_common(1)[0][0] if fabrics else "",
                "sizes": list(dict.fromkeys(sizes)),
                "modelImages": model_images,
                "fabricImages": fabric_images,
                "sourceRows": list(range(excel_row, block_end + 1)),
                "cuttingPassportNo": clean(safe_cell(rows[excel_row - 1], 3)),
                "productionDateSerial": safe_cell(rows[excel_row - 1], 2),
            }
        )

    grouped: dict[str, dict] = {}
    duplicate_rows = 0
    for record in raw_records:
        code = record["code"]
        current = grouped.get(code)
        if current is None:
            current = dict(record)
            current["conflicts"] = {"fabrics": [], "modelImages": [], "fabricImages": []}
            grouped[code] = current
            continue
        duplicate_rows += 1
        for size in record["sizes"]:
            if size not in current["sizes"]:
                current["sizes"].append(size)
        for source_row in record["sourceRows"]:
            if source_row not in current["sourceRows"]:
                current["sourceRows"].append(source_row)
        if record["fabric"] and record["fabric"] != current["fabric"]:
            current["conflicts"]["fabrics"] = list(dict.fromkeys([current["fabric"], record["fabric"]]))
        for field in ("modelImages", "fabricImages"):
            combined = unique_images(current[field] + record[field])
            if len(combined) > len(current[field]):
                current[field] = combined
            if len(combined) > 1:
                current["conflicts"][field] = combined

    records = list(grouped.values())
    referenced_hashes = {
        image["sha256"]
        for record in records
        for field in ("modelImages", "fabricImages")
        for image in record[field]
    }
    stats = {
        "sheetRows": len(rows),
        "identityRows": len(raw_records),
        "records": len(records),
        "duplicateIdentityRowsConsolidated": duplicate_rows,
        "anchoredImages": len(anchors),
        "uniqueReferencedImages": len(referenced_hashes),
        "recordsWithoutModelImages": sum(not record["modelImages"] for record in records),
        "recordsWithoutFabricImages": sum(not record["fabricImages"] for record in records),
        "recordsWithoutFabric": sum(not record["fabric"] for record in records),
        "recordsWithoutSize": sum(not record["sizes"] for record in records),
    }
    manifest = {
        "source": args.workbook.name,
        "stats": stats,
        "records": records,
        "skippedRows": [],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
