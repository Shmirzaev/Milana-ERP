from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict

from app.db.session import SessionLocal
from app.models import Model


CONFUSABLES = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
    }
)


def normalized_code(value: str) -> str:
    code = unicodedata.normalize("NFKC", str(value or "")).upper().translate(CONFUSABLES)
    code = re.sub(r"[‐‑‒–—―]", "-", code)
    code = re.sub(r"\s+", "", code)
    parts = code.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        parts[1] = str(int(parts[1]))
        code = "-".join(parts)
    return code


def main() -> None:
    with SessionLocal() as db:
        models = db.query(Model.id, Model.code).order_by(Model.id).all()
    groups: dict[str, list[dict]] = defaultdict(list)
    for model_id, code in models:
        groups[normalized_code(code)].append({"id": model_id, "code": code})
    collisions = {key: rows for key, rows in groups.items() if len(rows) > 1}
    print(json.dumps({"models": len(models), "logical_duplicate_groups": collisions}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
