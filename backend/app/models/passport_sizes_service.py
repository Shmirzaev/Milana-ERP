"""Resolve passport ranges against the exact order labels, without guessing size steps."""
import re


def selected_sizes(value: str | None, sizes: list[str]) -> list[str]:
    selected = str(value or "").strip().removesuffix(" ×2")
    choices = list(dict.fromkeys(str(size).strip() for size in sizes if str(size).strip()))
    if selected in choices:
        return [selected]
    if "," in selected:
        requested = {part.strip() for part in selected.split(",")}
        return [size for size in choices if size in requested]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", selected)
    if match:
        start, end = map(float, match.groups())
        return [size for size in choices if re.fullmatch(r"\d+(?:\.\d+)?", size) and start <= float(size) <= end]
    return []


def passport_order_sizes(passport) -> list[str]:
    order = getattr(passport, "production_order", None)
    return list(dict.fromkeys(str(row.size).strip() for row in (order.items if order else []) if str(row.size or "").strip()))


def size_count_from_range(value: str | None, sizes: list[str] | None = None) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if sizes:
        return len(selected_sizes(text, sizes)) * (2 if text.endswith(" ×2") else 1)
    if text.endswith(" ×2"):
        # Explicit model labels: a combined size such as 40-42 is one size.
        return 2 * len({part.strip() for part in text[:-3].split(",") if part.strip()})
    if "," in text:
        return len({part.strip() for part in text.split(",") if part.strip()})
    if "-" not in text:
        return 1
    start_text, end_text = [part.strip() for part in text.split("-", 1)]
    try:
        start = float(start_text)
        end = float(end_text)
    except ValueError:
        return 1
    if start >= end:
        return 1
    step = 2 if start.is_integer() and end.is_integer() and end - start >= 2 else 1
    count = 0
    current = start
    while current <= end:
        count += 1
        current += step
    return count
