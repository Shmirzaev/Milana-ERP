"""60 × 40 mm payroll allocation labels; rendering never changes payroll."""
from html import escape

from app.services.barcode import qr_png_data_uri


def split_label_card(label, employee, token: str) -> str:
    quantity = format(label.quantity, "f")
    if "." in quantity:
        quantity = quantity.rstrip("0").rstrip(".")
    lines = [
        ("operation", label.operation_name), ("model", label.model_code),
        ("reference", label.production_no or label.sales_order_no),
        ("batch", label.batch_no), ("employee", employee.full_name),
        ("quantity", f'{employee.employee_no or str(employee.id).zfill(4)} · {label.size or ""} · {quantity}'),
    ]
    details = "".join(f'<p class="{kind}">{escape(str(value or ""))}</p>' for kind, value in lines if value)
    return (f'<article><div class="details">{details}</div><div class="qr">'
            f'<img alt="QR" src="{qr_png_data_uri(token)}"><p>{escape(token)}</p></div></article>')


def split_labels_html(cards: list[str]) -> str:
    return '''<!doctype html><html><head><meta charset="utf-8"><title>Payroll stickers</title><style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;background:#fff}
article{width:60mm;height:40mm;padding:2mm;display:grid;grid-template-columns:minmax(0,1fr) 19mm;gap:2mm;break-inside:avoid;break-after:page}
article:last-child{break-after:auto}p{margin:0}
.details{min-width:0;height:36mm;display:flex;flex-direction:column;justify-content:space-between;overflow-wrap:anywhere;font-size:9.5pt;line-height:1.05}
.operation,.employee{font-size:1.05em;font-weight:700}.model,.quantity{font-weight:700}
.reference{font-size:.8em}.qr{width:19mm;align-self:center;text-align:center}
.qr img{display:block;width:19mm;height:19mm;object-fit:contain}.qr p{margin-top:1mm;font-size:8.5pt;font-weight:700;white-space:nowrap}
@page{size:60mm 40mm;margin:0}@media print{button{display:none}}
@media screen{body{background:#eee}article{background:#fff;margin:8px}}
</style></head><body><button onclick="window.print()">Print / Печать / Chop etish</button>''' + ''.join(cards) + '''<script>
function fitLabels(){document.querySelectorAll('.details').forEach(el=>{el.style.fontSize='9.5pt';let size=9.5;while(el.scrollHeight>el.clientHeight+1&&size>7){size-=.25;el.style.fontSize=size+'pt';}});}
window.addEventListener('load',fitLabels);window.addEventListener('beforeprint',fitLabels);
</script></body></html>'''
