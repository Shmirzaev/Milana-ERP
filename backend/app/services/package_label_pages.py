"""Explicit A4 pagination keeps page numbers beside the four physical labels."""
from html import escape


def label_document(title: str, cards: list[str], label_css: str, summary: str = "") -> str:
    total = max(1, (len(cards) + 3) // 4)
    pages = []
    for index in range(total):
        labels = "".join(cards[index * 4:(index + 1) * 4])
        pages.append(
            f"<section class='label-page'><div class='sheet'>{labels}</div>"
            f"<footer class='page-number'>Page / Страница / Sahifa {index + 1} / {total}</footer></section>"
        )
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>
<style>@page{{size:A4 portrait;margin:5mm}}{label_css}
.label-page{{width:200mm;height:287mm;display:flex;flex-direction:column;break-after:page;page-break-after:always}}
.label-page:last-of-type{{break-after:auto;page-break-after:auto}}
.sheet{{display:grid;grid-template-columns:repeat(2,98.5mm);gap:3mm}}
.label-page .label{{height:139mm}}
.page-number{{margin-top:auto;height:6mm;text-align:center;font-size:8pt;line-height:6mm}}
.run-summary{{padding:3mm;font-size:9pt}}
@media print{{.run-summary{{display:none}}}}
</style></head><body>{summary}{''.join(pages)}
<button class='print-button' onclick='window.print()'>Print / Печать / Chop etish</button></body></html>"""
