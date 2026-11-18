"""Read the eleven owner-supplied workbooks; emit a deterministic import manifest.

Workbook text is data only. Formula evaluation accepts arithmetic and same-sheet
cell references, never Python calls or executable spreadsheet content.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import operator
from pathlib import Path
import re
import sys
import unicodedata

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / "Downloads" / "Telegram Desktop"
OUT = ROOT / "outputs" / "accessories-opening-20261118"
CONFIG = [
    # filename, code, family, identifying col, received, balance, issue cols, reject, return
    ("ДОНА КУРЖАВАЛАР.xlsx", "LPC", "Куржава дона / Штучное кружево", "E", "G", "Y", "I K M O Q S U", "W", "X"),
    ("КУРЖАВАЛАР.xlsx", "LAC", "Куржава / Кружево", "F", "J", "AB", "L N P R T V X", "Z", "AA"),
    ("РЕЗИНКА.xlsx", "ELA", "Резинка", "D", "E", "U", "G I K M O Q", "S", "T"),
    ("Тикув иплар.xlsx", "THR", "Тикув ипи / Нитки", "E", "H", "X", "J L N P R T", "V", "W"),
    ("ТЕСМАЛАР.xlsx", "TAP", "Тесма / Тесьма", "D", "I", "AC", "K M O Q S U W Y", "AA", "AB"),
    ("ПАКЕТЛАР.xlsx", "BAG", "Пакет", "D", "E", "N", "G I K", "M", None),
    ("ПАЧКА ТЕСМАЛАР.xlsx", "TPB", "Тесма боглам / Тесьма в мотках", "D", "H", "V", "J L N P R", "T", "U"),
    ("МЕТАЛ АКСЕССУАРЛАР,.xlsx", "MET", "Металл ва безак / Фурнитура", "E", "H", "V", "J L N P R", "T", "U"),
    ("ЗАМОК 2024 ДЕКАБР.xlsx", "ZIP", "Замок / Молния", "D", "I", "Y", "K M O Q S U", "W", "X"),
    ("КАРТАЛАР.xlsx", "TAG", "Карта / Бирка", "D", "E", "Y", "G I K M O Q S U", "W", "X"),
    ("ТУГМА.xlsx", "BTN", "Тугма / Пуговица", "D", "G", "Y", "I K M O Q S U", "W", "X"),
]


def clean(value):
    return " ".join(unicodedata.normalize("NFKC", str(value if value is not None else "")).split())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evaluator(cells):
    memo = {}
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def calculate(address, trail=()):
        if address in memo:
            return memo[address]
        if address in trail:
            raise ValueError("Circular reference: " + address)
        value = cells.get(address)
        if value is None:
            return Decimal(0)
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if not isinstance(value, str) or not value.startswith("="):
            raise ValueError("Non-numeric precedent: " + address)

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return Decimal(str(node.value))
            if isinstance(node, ast.Name) and re.fullmatch(r"[A-Z]+[1-9][0-9]*", node.id):
                return calculate(node.id, trail + (address,))
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                return ops[type(node.op)](visit(node.left), visit(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            raise ValueError("Unsupported formula: " + address)

        try:
            tree = ast.parse(value[1:].replace("$", ""), mode="eval")
        except SyntaxError as error:
            raise ValueError("Unsupported formula: " + address) from error
        result = visit(tree)
        if not result.is_finite():
            raise ValueError("Non-finite quantity")
        memo[address] = result
        return result

    return calculate


def quantity(value):
    rounded = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if value != rounded:
        raise ValueError("Quantity exceeds ERP precision")
    return format(rounded, "f")


def build():
    rows, sources = [], []
    for filename, code, family, label, received, balance, issue, reject, returned in CONFIG:
        path = SOURCE / filename
        sources.append({"file": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
        cached_wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sheet_index, sheet in enumerate(wb, 1):
            cells = {c.coordinate: c.value for row in sheet.iter_rows() for c in row if c.value is not None}
            cached = {c.coordinate: c.value for row in cached_wb[sheet.title].iter_rows() for c in row if c.value is not None}
            calc = evaluator(cells)
            for address, value in cells.items():
                if isinstance(value, str) and value.startswith("="):
                    result = calc(address)
                    if address in cached and abs(result - Decimal(str(cached[address]))) > Decimal("0.00001"):
                        raise ValueError(f"Cached formula mismatch: {filename}/{sheet.title}/{address}")
            for number in range(4, sheet.max_row + 1):
                if cells.get(f"{label}{number}") is None:
                    # Template rows and floating photos cannot create stock.
                    if calc(f"{received}{number}") != 0 or calc(f"{balance}{number}") != 0:
                        raise ValueError(f"Unnamed stock: {filename}/{sheet.title}/{number}")
                    continue
                raw = {re.sub(r"\d+$", "", a): v for a, v in cells.items() if re.fullmatch(r"[A-Z]+" + str(number), a)}
                raw = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in raw.items()}
                remaining = calc(f"{balance}{number}")
                expected = calc(f"{received}{number}") - sum((calc(f"{c}{number}") for c in issue.split()), Decimal(0)) - calc(f"{reject}{number}") + (calc(f"{returned}{number}") if returned else Decimal(0))
                if remaining < 0 or remaining != expected:
                    raise ValueError(f"Unreconciled closing balance: {filename}/{sheet.title}/{number}")
                val = lambda c: clean(raw.get(c))
                title = val(label)
                origin = val("D") or val("E") if code == "LAC" else val("D") if code in ("LPC", "MET") else val("C")
                color_code = val("E") if code in ("THR", "ZIP") else val("F") if code == "TAP" else ""
                unit = {"LPC": "pcs", "LAC": "m", "ELA": "kg", "THR": "pcs", "TAP": "m", "BAG": "kg", "TPB": "bundle", "MET": "pcs", "ZIP": "pcs", "TAG": "pcs", "BTN": "pcs"}[code]
                name_parts = [family]
                if code == "MET" and "ТУГМА" in title.upper():
                    name_parts[0] = "Тугма / Пуговица — Металл"
                if code == "ELA":
                    name_parts += ["ОК", title + " см", origin]
                    identity = [code, val("C").upper(), title]
                elif code == "THR":
                    name_parts += [origin, val("D"), color_code]
                    identity = [code, origin.upper(), val("D").upper(), color_code.upper()]
                elif code in ("TAP", "TPB"):
                    width = val("E")
                    name_parts += [title, width + ("" if re.search(r"[A-Za-zА-Яа-я]", width) else " см") if width else "", color_code, origin]
                    identity = [code, title.upper(), width.upper(), color_code.upper(), origin.upper()]
                elif code == "ZIP":
                    name_parts += [title, val("F") + " см", color_code]
                    identity = [code, title.upper(), val("F"), color_code.upper()]
                elif code == "BTN":
                    size = val("E")
                    name_parts += [title, size + (" L" if size in {"24", "44", "48", "54"} else " мм")]
                    identity = [code, title.upper(), size]
                else:
                    name_parts += [title]
                    identity = [code, title.upper()]
                reasons = []
                status = "ready" if remaining else "zero_balance"
                if code == "TAG" and sheet.title.strip() != "КАРТАЛАР 2026":
                    status = "historical_excluded"
                if code == "LPC" and (re.search(r"ЖУФТ|2\s*ТАЛИК", title, re.I) or re.search(r"\*2\b|\b2\*", str(raw.get(received, "")))):
                    reasons.append("Owner requested hold: pieces versus pairs/sets varies")
                if f"{received}{number}" not in cells:
                    reasons.append("Pack count exists but base quantity is missing")
                row = dict(source_file=filename, source_sha256=sources[-1]["sha256"], source_sheet=sheet.title, source_row=number,
                           source_key=f"{code}:{sheet_index}:{number}", family_code=code, family=family, category="packaging" if code in ("BAG", "TAG") else "accessory",
                           unit=unit, name=" — ".join(p for p in name_parts if p), identity=identity, quantity=quantity(remaining),
                           source_received=quantity(calc(f"{received}{number}")), source_received_date=raw.get("B"), origin=origin,
                           color_code=color_code or None, source_number=val("A"), status=status, reasons=reasons, raw=raw)
                rows.append(row)
        wb.close()
        cached_wb.close()

    # Same generic colour/name does not prove identical lace design, button
    # construction, zipper type or bag artwork. Retain these pending inspection.
    ambiguous = defaultdict(list)
    for row in rows:
        uncertain_tape = row["family_code"] == "TAP" and not row["color_code"]
        if row["status"] != "historical_excluded" and (row["family_code"] in {"LPC", "LAC", "BTN", "ZIP", "BAG"} or uncertain_tape):
            ambiguous[tuple(row["identity"])].append(row)
    for members in ambiguous.values():
        if len(members) > 1:
            for row in members:
                row["reasons"].append("Repeated description: confirm same specification or separate design")
    products = {}
    for row in rows:
        if row["reasons"] and row["status"] != "historical_excluded":
            row["status"] = "pending"
        if row["status"] not in ("ready", "zero_balance"):
            continue
        identity_hash = digest(row["identity"])
        sku = f"MIL-{row['family_code']}-{identity_hash[:12].upper()}"
        row["sku"] = sku
        row["batch_no"] = f"MIL-OPEN26-{row['source_key'].replace(':', '-')}"
        if sku not in products:
            products[sku] = {"sku": sku, "name": row["name"], "category": row["category"], "unit": row["unit"], "family_code": row["family_code"], "default_cost": "0.0000", "source_keys": []}
        if products[sku]["name"] != row["name"]:
            # Whitespace/case normalisation is the only permitted difference.
            if products[sku]["name"].upper() != row["name"].upper():
                raise ValueError("Conflicting display name for one product identity")
        products[sku]["source_keys"].append(row["source_key"])
    names = [p["name"].lower() for p in products.values()]
    if len(names) != len(set(names)):
        raise ValueError("Proposed active product names collide")
    summary = {"source_rows": len(rows), "products": len(products), "status_counts": dict(Counter(r["status"] for r in rows)), "family_units": []}
    for code in sorted({r["family_code"] for r in rows}):
        group = [r for r in rows if r["family_code"] == code]
        ready = [r for r in group if r["status"] == "ready"]
        summary["family_units"].append({"family_code": code, "source_rows": len(group), "ready_batches": len(ready), "pending_rows": sum(r["status"] == "pending" for r in group), "unit": group[0]["unit"], "quantity": quantity(sum((Decimal(r["quantity"]) for r in ready), Decimal(0)))})
    payload = {"version": 1, "operation": "MILANA_ACCESSORIES_OPENING_20261118", "warehouse_id": 2, "warehouse_name": "Accessory Storage", "warehouse_department": "STR", "production_release": "20261116_130518", "production_manifest": "bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40", "database_revision": "0157_package_allocation_items", "valuation": "provisional_zero_owner_approval_required", "sources": sources, "products": sorted(products.values(), key=lambda p: p["sku"]), "rows": rows, "summary": summary}
    return payload


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    payload = build()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "manifest.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = [r for r in payload["rows"] if r["status"] == "pending"]
    lines = ["# Milana accessories awaiting clarification", "", f"These {len(pending)} source rows are excluded from the opening-stock import. Quantities below retain the workbook's stated unit until confirmed.", "", "| File | Sheet / row | Description | Source balance | Reason |", "| --- | --- | --- | ---: | --- |"]
    for row in pending:
        cells = [row["source_file"], f"{row['source_sheet']} / {row['source_row']}", row["name"], f"{row['quantity']} {row['unit']}", "; ".join(row["reasons"])]
        lines.append("| " + " | ".join(str(v).replace("|", "/") for v in cells) + " |")
    (OUT / "pending-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"manifest_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), **payload["summary"]}, ensure_ascii=False))
