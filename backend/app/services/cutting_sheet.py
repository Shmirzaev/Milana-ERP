from __future__ import annotations

from collections import defaultdict
from datetime import timedelta, timezone
from html import escape
from math import floor

from sqlalchemy.orm import Session, selectinload

from app.core.dt import as_utc
from app.models import (
    Brand,
    Bundle,
    CuttingPassport,
    CuttingRecord,
    Model,
    ModelBOM,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    StockBatch,
    User,
    WorkOrder,
)
from app.services.label_images import fabric_label_image_src, model_label_image_src


_TASHKENT = timezone(timedelta(hours=5), name="Asia/Tashkent")
_ACCESSORY_ROWS = (
    "Tesma",
    "Tugma",
    "Zamok",
    "Ribana",
    "Razmer etiket",
    "Beyka",
    "Kurjava",
    "IP",
    "Mato turi",
    "Fabrika nomi",
)
_ACCESSORY_KEYWORDS = {
    "Tesma": ("tesma", "tape", "webbing"),
    "Tugma": ("tugma", "button"),
    "Zamok": ("zamok", "zipper", "fermuar"),
    "Ribana": ("ribana", "ribbing", "rib"),
    "Razmer etiket": ("razmer etiket", "size label", "size tag"),
    "Beyka": ("beyka", "beika", "binding", "bias"),
    "Kurjava": ("kurjava",),
    "IP": (" ip ", "thread", "yarn"),
}


def _h(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _text(value: object) -> str:
    return str(value or "").strip()


def _general(model: Model | None) -> dict:
    details = model.details_json if model else None
    if not isinstance(details, dict):
        return {}
    value = details.get("general")
    return value if isinstance(value, dict) else {}


def _first(mapping: dict, *keys: str) -> str:
    for key in keys:
        value = _text(mapping.get(key))
        if value:
            return value
    return ""


def _formatted_datetime(value) -> str:
    normalized = as_utc(value)
    if not normalized:
        return ""
    return normalized.astimezone(_TASHKENT).strftime("%d.%m.%Y, %H:%M")


def _format_quantity(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if number == 0:
        return ""
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _batch_label(db: Session, batch: ProductionBatch | None, production_order_id: int) -> str:
    if not batch:
        return ""
    total = db.query(ProductionBatch.id).filter(ProductionBatch.production_order_id == production_order_id).count()
    if batch.batch_index and total:
        return f"{batch.batch_index}/{total}"
    return _text(batch.batch_no or batch.name)


def _scaled_size_plan(items: list[ProductionOrderItem], target_total: int) -> tuple[list[str], dict[str, int]]:
    sizes: list[str] = []
    totals: dict[str, int] = defaultdict(int)
    for item in items:
        size = _text(item.size)
        if not size:
            continue
        if size not in totals:
            sizes.append(size)
        totals[size] += max(0, int(item.planned_quantity or 0))

    source_total = sum(totals.values())
    target = max(0, int(target_total or 0))
    if not sizes or source_total <= 0 or target <= 0:
        return sizes, {size: 0 for size in sizes}
    if target == source_total:
        return sizes, dict(totals)

    scaled: dict[str, int] = {}
    remainders: list[tuple[float, int, str]] = []
    used = 0
    for index, size in enumerate(sizes):
        exact = target * totals[size] / source_total
        quantity = floor(exact)
        scaled[size] = quantity
        used += quantity
        remainders.append((exact - quantity, index, size))
    remainders.sort(key=lambda row: (-row[0], row[1]))
    for _, _, size in remainders[: target - used]:
        scaled[size] += 1
    return sizes, scaled


def _scoped_bundles(
    db: Session,
    record: CuttingRecord,
    work_order: WorkOrder,
    bundle_ids: list[int],
) -> list[Bundle]:
    query = db.query(Bundle).filter(Bundle.production_order_id == work_order.production_order_id)
    if record.production_batch_id is None:
        query = query.filter(Bundle.production_batch_id.is_(None))
    else:
        query = query.filter(Bundle.production_batch_id == record.production_batch_id)

    if bundle_ids:
        return query.filter(Bundle.id.in_(bundle_ids)).order_by(Bundle.id.asc()).all()

    record_query = db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id == work_order.id)
    if record.production_batch_id is None:
        record_query = record_query.filter(CuttingRecord.production_batch_id.is_(None))
    else:
        record_query = record_query.filter(CuttingRecord.production_batch_id == record.production_batch_id)
    if record_query.count() != 1:
        return []
    return query.order_by(Bundle.id.asc()).all()


def _bom_value(rows: list[ModelBOM], keywords: tuple[str, ...]) -> str:
    matches: list[str] = []
    for row in rows:
        item = row.item
        haystack = f" {_text(item.sku)} {_text(item.name)} ".lower() if item else ""
        if not any(keyword in haystack for keyword in keywords):
            continue
        label = _text(item.name or item.sku)
        quantity = _format_quantity(row.quantity_per_piece)
        unit = _text(row.unit)
        value = " - ".join(part for part in (label, f"{quantity} {unit}".strip()) if part)
        if value and value not in matches:
            matches.append(value)
    return "; ".join(matches)


def _accessory_values(
    rows: list[ModelBOM],
    fabric_batch: StockBatch | None,
    bundles: list[Bundle],
) -> dict[str, str]:
    values = {label: "" for label in _ACCESSORY_ROWS}
    for label, keywords in _ACCESSORY_KEYWORDS.items():
        values[label] = _bom_value(rows, keywords)

    fabric_item = fabric_batch.item if fabric_batch else None
    if not fabric_item:
        fabric_row = next(
            (
                row
                for row in rows
                if row.item and _text(row.item.category).lower() in {"fabric", "semi_finished"}
            ),
            None,
        )
        fabric_item = fabric_row.item if fabric_row else None
    values["Mato turi"] = _text(fabric_item.name or fabric_item.sku) if fabric_item else ""

    factory_names = []
    for code in (_text(bundle.sewing_factory_code).upper() for bundle in bundles):
        name = "Besttex" if code == "BST" else "Eco Cotton" if code == "ECO" else "Milana" if code == "MIL" else code
        if name and name not in factory_names:
            factory_names.append(name)
    values["Fabrika nomi"] = ", ".join(factory_names)
    return values


def _model_identity(model: Model | None, passport: CuttingPassport | None) -> dict[str, str]:
    general = _general(model)
    model_no = _first(general, "model_no", "modelNo")
    article = _first(general, "variant_no", "variantNo", "article", "artikul")
    if not model_no:
        model_no = _text(passport.model_code if passport else None) or _text(model.code if model else None)
    if not article:
        article = _text(passport.variant if passport else None)
    qolip = _first(
        general,
        "qolip_no",
        "qolipNo",
        "mold_no",
        "moldNo",
        "pattern_no",
        "patternNo",
    ) or _text(passport.mold_no if passport else None)
    detskiy = _first(general, "detskiy", "kids", "children")
    return {"model": model_no, "article": article, "qolip": qolip, "detskiy": detskiy}


def _table_row(label: str, values: list[str], total: str = "", highlight: bool = False) -> str:
    row_class = " class='cut-row'" if highlight else ""
    cells = "".join(f"<td>{_h(value)}</td>" for value in values)
    return f"<tr{row_class}><th>{_h(label)}</th>{cells}<td class='total'>{_h(total)}</td></tr>"


def render_cutting_sheet_html(db: Session, record: CuttingRecord, bundle_ids: list[int] | None = None) -> str:
    work_order = db.get(WorkOrder, record.work_order_id)
    if not work_order:
        raise ValueError("Cutting work order not found")
    production_order = db.get(ProductionOrder, work_order.production_order_id)
    if not production_order:
        raise ValueError("Production order not found")

    model = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.bom).selectinload(ModelBOM.item),
            selectinload(Model.bom).selectinload(ModelBOM.stock_batch),
        )
        .filter(Model.id == production_order.model_id)
        .first()
    )
    batch = db.get(ProductionBatch, record.production_batch_id) if record.production_batch_id else None
    fabric_batch = db.get(StockBatch, record.fabric_batch_id) if record.fabric_batch_id else None
    passport = (
        db.query(CuttingPassport)
        .filter(CuttingPassport.production_order_id == production_order.id)
        .order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
        .first()
    )
    sheet_brand_id = production_order.brand_id or (model.brand_id if model else None)
    brand = db.get(Brand, sheet_brand_id) if sheet_brand_id else None
    operator = db.get(User, record.operator_id) if record.operator_id else None
    bundles = _scoped_bundles(db, record, work_order, bundle_ids or [])

    items = (
        db.query(ProductionOrderItem)
        .filter(ProductionOrderItem.production_order_id == production_order.id)
        .order_by(ProductionOrderItem.id.asc())
        .all()
    )
    planned_total = int(batch.planned_quantity if batch else production_order.planned_quantity or 0)
    sizes, planned_by_size = _scaled_size_plan(items, planned_total)
    cut_by_size: dict[str, int] = defaultdict(int)
    for bundle in bundles:
        size = _text(bundle.size)
        if size and size not in sizes:
            sizes.append(size)
        cut_by_size[size] += int(bundle.quantity or 0)
    while len(sizes) < 5:
        sizes.append("")

    identity = _model_identity(model, passport)
    accessory_values = _accessory_values(list(model.bom or []) if model else [], fabric_batch, bundles)
    if not accessory_values["Mato turi"] and passport:
        accessory_values["Mato turi"] = _text(passport.fabric_type)
    if float(record.beika_kg or 0) > 0:
        accessory_values["Beyka"] = f"{_format_quantity(record.beika_kg)} kg"
    if not accessory_values["Ribana"] and passport and float(passport.ribana_per_piece_kg or 0) > 0:
        accessory_values["Ribana"] = f"{_format_quantity(passport.ribana_per_piece_kg)} kg/pc"
    image_src = model_label_image_src(model)
    image_html = (
        f"<img src='{_h(image_src)}' alt='Model image'>"
        if image_src
        else "<div class='empty-photo'></div>"
    )
    fabric_image_src = fabric_label_image_src(model)
    fabric_image_html = (
        f"<img src='{_h(fabric_image_src)}' alt='Fabric picture'>"
        if fabric_image_src
        else ""
    )
    cutting_date = _formatted_datetime(record.created_at)
    order_no = _text(production_order.order_no or (passport.order_no if passport else None))
    kroy_no = _text(passport.passport_no if passport else None)
    etiket = _text(brand.name if brand else None)
    batch_label = _batch_label(db, batch, production_order.id)
    report_ref = f"CUT-{record.id}"

    size_values = sizes
    planned_values = [_format_quantity(planned_by_size.get(size, 0)) for size in sizes]
    cut_values = [_format_quantity(cut_by_size.get(size, 0)) for size in sizes]
    blank_values = ["" for _ in sizes]
    process_rows = "".join(
        (
            _table_row("Razmer", size_values, "TOTAL"),
            _table_row("Buyurtma", planned_values, _format_quantity(planned_total)),
            _table_row("Kesildi", cut_values, _format_quantity(record.cut_pieces), highlight=True),
            _table_row("Buyurtma", blank_values),
            _table_row("Kesildi", blank_values),
            _table_row("Pechat", blank_values),
            _table_row("Tikuv", blank_values),
            _table_row("2-sort", blank_values),
            _table_row("Dazmol", blank_values),
            _table_row("2-sort", blank_values),
            _table_row("Brak", blank_values, _format_quantity(record.defective_pieces)),
            _table_row("Upakovka", blank_values),
        )
    )
    accessory_rows = "".join(
        f"<tr><th>{_h(label)}</th><td>{_h(accessory_values[label])}</td></tr>"
        for label in _ACCESSORY_ROWS
    )
    operator_note = f"Operator: {_text(operator.name)}" if operator else ""

    return f"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8"><title>Cutting sheet {report_ref}</title>
<style>
@page{{size:A4 landscape;margin:7mm}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0;background:#ececeb;color:#17191a;font-family:Arial,sans-serif}}
.toolbar{{display:flex;justify-content:flex-end;padding:10px;background:#fff;border-bottom:1px solid #d1d4d3}}
.toolbar button{{border:1px solid #2f6049;border-radius:7px;background:#2f6049;color:#fff;padding:8px 14px;font:600 14px Arial;cursor:pointer}}
.sheet{{width:283mm;height:196mm;margin:10px auto;background:#fff;border:1px solid #17191a;padding:0;overflow:hidden}}
.meta{{height:12mm;display:grid;grid-template-columns:1fr 1fr 1fr;align-items:center;border-bottom:1px solid #9fa5a7;font-size:8pt}}
.meta strong{{font-size:9pt}} .meta .center{{text-align:center}} .meta .right{{text-align:right}}
.top{{height:64mm;display:grid;grid-template-columns:46% 54%;gap:2mm;margin-top:2mm}}
.lower{{height:105mm;min-height:0;display:grid;grid-template-columns:46% 54%;gap:2mm;margin-top:2mm;overflow:hidden}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}} th,td{{border:1px solid #aeb5b8;padding:1.2mm;vertical-align:middle}}
th{{background:#e8ecea;text-align:left;font-weight:700}} td{{text-align:center}}
.identity{{height:100%;font-size:8pt}} .identity .title-row{{height:9mm}} .identity .photo-cell{{padding:0;background:#f3f5f4}}
.identity .photo{{height:55mm;display:flex;align-items:center;justify-content:center;padding:3mm}}
.identity .photo img{{display:block;max-width:100%;max-height:100%;object-fit:contain}}
.empty-photo{{width:100%;height:100%}}
.identity .field-label{{width:52%;font-weight:700;background:#e8ecea;text-align:left}}
.identity .field-value{{height:9.1mm;text-align:center}}
.process-wrap{{height:100%;display:flex;flex-direction:column}}
.summary{{height:9mm;font-size:6.7pt}} .summary th,.summary td{{padding:.8mm;text-align:center}}
.process{{height:55mm;font-size:6.6pt}} .process th{{width:24mm;padding:.5mm 1.2mm}}
.process td{{padding:.45mm;text-align:center}} .process .total{{font-weight:700;background:#f3f5f4}}
.process .cut-row th{{background:#dcecdf;color:#2e674e}} .process .cut-row td{{background:#f3faf5;color:#2e674e;font-weight:700}}
.accessories{{height:100%;min-height:0;font-size:7.4pt}} .accessories caption{{height:8mm;padding:2mm;text-align:left;background:#17191a;color:#fff;font-weight:700}}
.accessories th{{width:46%;height:9.7mm;padding-left:3mm}} .accessories td{{height:9.7mm;text-align:left;padding-left:3mm}}
.samples{{height:100%;min-height:0;display:grid;grid-template-columns:1fr 1fr;border:1px solid #aeb5b8;overflow:hidden}}
.sample-column{{min-width:0;min-height:0;display:grid;grid-template-rows:9mm minmax(0,1fr);overflow:hidden}}
.sample-column.right{{grid-template-rows:9mm minmax(0,1fr) 9mm minmax(0,1fr)}}
.sample-column+.sample-column{{border-left:1px solid #aeb5b8}}
.sample-title{{display:flex;min-height:0;align-items:center;justify-content:center;background:#e8ecea;border-bottom:1px solid #aeb5b8;font-size:8pt;font-weight:700}}
.sample-box{{min-height:0;overflow:hidden;background:#fff}}
.fabric-sample{{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr)}}
.fabric-photo{{display:flex;min-height:0;align-items:center;justify-content:center;overflow:hidden;padding:3mm;border-bottom:1px solid #aeb5b8}}
.fabric-photo img{{display:block;width:100%;height:100%;object-fit:contain}}
.sample-column.right .sample-title.print{{border-top:1px solid #aeb5b8}}
.footer{{height:8mm;display:flex;align-items:end;justify-content:space-between;border-top:1px solid #aeb5b8;margin-top:2mm;padding-top:1.5mm;font-size:6pt;color:#61686d}}
@media print{{html,body{{background:#fff}} .toolbar{{display:none}} .sheet{{margin:0;border:0;padding:0;width:283mm;height:196mm}}}}
</style></head>
<body><div class="toolbar"><button onclick="window.print()">Print / Save PDF</button></div>
<main class="sheet">
  <header class="meta"><div><strong>MILANA ERP</strong><br>{_h(cutting_date)}</div><div class="center"><strong>REPORT</strong>{f' | BATCH {_h(batch_label)}' if batch_label else ''}</div><div class="right"><strong>{_h(report_ref)}</strong><br>Page 1 / 1</div></header>
  <section class="top">
    <table class="identity">
      <tr class="title-row"><th>Model</th><td>{_h(identity['model'])}</td><th>Qolip No</th><td>{_h(identity['qolip'])}</td></tr>
      <tr><td class="photo-cell" rowspan="6" colspan="2"><div class="photo">{image_html}</div></td><th class="field-label">Artikul</th><td class="field-value">{_h(identity['article'])}</td></tr>
      <tr><th class="field-label">Zakaz No</th><td class="field-value">{_h(order_no)}</td></tr>
      <tr><th class="field-label">Bichilgan sana</th><td class="field-value">{_h(cutting_date)}</td></tr>
      <tr><th class="field-label">Etiket</th><td class="field-value">{_h(etiket)}</td></tr>
      <tr><th class="field-label">Kroy No</th><td class="field-value">{_h(kroy_no)}</td></tr>
      <tr><th class="field-label">Detskiy</th><td class="field-value">{_h(identity['detskiy'])}</td></tr>
    </table>
    <div class="process-wrap">
      <table class="summary"><tr><th>Sana</th><td>{_h(cutting_date)}</td><th>Buyurtma soni</th><td>{_h(_format_quantity(planned_total))}</td><th>Bichilgan soni</th><td><strong>{_h(_format_quantity(record.cut_pieces))}</strong></td></tr></table>
      <table class="process"><tbody>{process_rows}</tbody></table>
    </div>
  </section>
  <section class="lower">
    <table class="accessories"><caption>Accessories / Material</caption><tbody>{accessory_rows}</tbody></table>
    <div class="samples">
      <div class="sample-column"><div class="sample-title">Mato namuna</div><div class="sample-box fabric-sample"><div class="fabric-photo">{fabric_image_html}</div><div></div></div></div>
      <div class="sample-column right"><div class="sample-title">Beyka namuna</div><div class="sample-box"></div><div class="sample-title print">Pechat</div><div class="sample-box"></div></div>
    </div>
  </section>
  <footer class="footer"><span>{_h(operator_note)}</span><span>Missing ERP values intentionally print blank.</span></footer>
</main></body></html>"""
