"""Build the reviewed second-pass old-ERP sticker import manifest.

Only rows previously classified as ``catalog_identity_missing`` are selected.
Globally unique numeric old-ERP variant numbers are authoritative; every other
row requires an explicit, photo-reviewed decision file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


CONFUSABLES = str.maketrans(
    {
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K",
        "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
        "І": "I", "Ј": "J",
    }
)


def clean(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())


def normalized_base(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper().translate(CONFUSABLES) if ch.isalnum())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    key = "".join(ch for ch in value if ch.isalnum())
    return str(int(key)) if key.isdigit() else key


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_guarded(path: Path, expected_hash: str) -> Any:
    actual = sha256(path)
    if actual != expected_hash:
        raise ValueError(f"{path.name} SHA-256 changed: {actual}")
    return json.loads(path.read_text(encoding="utf-8"))


def old_identity(row: dict[str, Any]) -> tuple[str, str]:
    return normalized_base(row.get("model_no")), normalized_variant(row.get("variant_no"))


def build(args: argparse.Namespace) -> dict[str, Any]:
    candidate = load_guarded(args.candidate, args.expected_candidate_sha256)
    classification = load_guarded(args.classification, args.expected_classification_sha256)
    old_payload = load_guarded(args.old_variants, args.expected_old_variants_sha256)
    decision_payload = load_guarded(args.decisions, args.expected_decisions_sha256)

    if candidate.get("version") != 1 or not isinstance(candidate.get("rows"), list):
        raise ValueError("Candidate manifest is not the reviewed version-1 source")
    if not isinstance(old_payload.get("rows"), list) or not old_payload.get("captured_at"):
        raise ValueError("Old ERP variant snapshot is incomplete")
    if decision_payload.get("version") != 1 or not isinstance(decision_payload.get("decisions"), dict):
        raise ValueError("Decision file is not a version-1 object")

    source_by_qr = {clean(row.get("qr_code")).casefold(): row for row in candidate["rows"]}
    selected = [
        row for row in classification.get("rows", [])
        if row.get("classification") == "catalog_identity_missing"
    ]
    if len(selected) != args.expected_rows:
        raise ValueError(f"Expected {args.expected_rows} catalog-missing rows, found {len(selected)}")

    old_rows = old_payload["rows"]
    old_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    old_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in old_rows:
        old_by_variant[normalized_variant(row.get("variant_no"))].append(row)
        old_by_identity[old_identity(row)].append(row)

    decisions = decision_payload["decisions"]
    used_decisions: set[str] = set()
    output_rows: list[dict[str, Any]] = []
    for classified in selected:
        qr = clean(classified.get("qr_code")).casefold()
        source = source_by_qr.get(qr)
        if not source:
            raise ValueError(f"{qr}: source row is absent from candidate manifest")
        original_model = clean(source.get("model_number"))
        original_article = clean(source.get("article"))
        decision = decisions.get(qr)
        old_match: dict[str, Any] | None = None
        if decision:
            used_decisions.add(qr)
            target_kind = clean(decision.get("target_kind")).casefold()
            basis = clean(decision.get("basis"))
            if target_kind == "catalog":
                target_model = clean(decision.get("model_number"))
                target_article = clean(decision.get("article"))
                matches = old_by_identity.get(
                    (normalized_base(target_model), normalized_variant(target_article)), []
                )
                if len(matches) != 1:
                    raise ValueError(f"{qr}: explicit catalog decision has {len(matches)} old ERP matches")
                old_match = matches[0]
            elif target_kind == "hidden_legacy":
                target_model = original_model
                target_article = original_article
            else:
                raise ValueError(f"{qr}: invalid decision target_kind {target_kind!r}")
        else:
            variant_key = normalized_variant(original_article)
            numeric_sticker = bool(re.fullmatch(r"V[\s_-]*\d+", original_article, flags=re.IGNORECASE))
            matches = old_by_variant.get(variant_key, [])
            if not numeric_sticker or variant_key == "1" or len(matches) != 1:
                raise ValueError(f"{qr}: non-unique identity requires an explicit decision")
            old_match = matches[0]
            target_kind = "catalog"
            target_model = clean(old_match["model_no"])
            target_article = clean(old_match["variant_no"])
            basis = "Globally unique old ERP variant number corrected the sticker workbook OCR model text."

        row = dict(source)
        row.update(
            {
                "target_kind": target_kind,
                "original_model_number": original_model,
                "original_article": original_article,
                "model_number": target_model,
                "article": target_article,
                "resolution_basis": basis,
                "review_basis": (
                    "Required sticker fields supplied in the user-completed workbook; "
                    "identity reviewed against old ERP and sticker photo."
                ),
                "old_erp_evidence": None,
            }
        )
        if old_match:
            row["old_erp_evidence"] = {
                "old_id": clean(old_match.get("old_id")),
                "model_no": clean(old_match.get("model_no")),
                "variant_no": clean(old_match.get("variant_no")),
                "edit_href": clean(old_match.get("edit_href")),
                "snapshot_captured_at": old_payload["captured_at"],
                "snapshot_sha256": args.expected_old_variants_sha256,
            }
        output_rows.append(row)

    unused = sorted(set(decisions) - used_decisions)
    if unused:
        raise ValueError(f"Decision file contains unused rows: {unused}")

    unique_identities = {
        (row["target_kind"], normalized_base(row["model_number"]), normalized_variant(row["article"]))
        for row in output_rows
    }
    payload = {
        "version": 2,
        "source": "Second-pass resolution of user-completed old-ERP sticker rows",
        "source_workbook_sha256": candidate["source_workbook_sha256"],
        "source_candidate_manifest_sha256": args.expected_candidate_sha256,
        "source_classification_sha256": args.expected_classification_sha256,
        "old_erp_variant_snapshot_sha256": args.expected_old_variants_sha256,
        "decision_file_sha256": args.expected_decisions_sha256,
        "expected_rows": len(output_rows),
        "expected_quantity": sum(int(row["quantity"]) for row in output_rows),
        "expected_known_weight_kg": str(
            sum(
                (Decimal(str(row["weight_kg"])) for row in output_rows if row.get("weight_kg") not in (None, "")),
                Decimal("0"),
            )
        ),
        "expected_null_weight_rows": sum(row.get("weight_kg") in (None, "") for row in output_rows),
        "expected_unique_identities": len(unique_identities),
        "expected_catalog_rows": sum(row["target_kind"] == "catalog" for row in output_rows),
        "expected_hidden_legacy_rows": sum(row["target_kind"] == "hidden_legacy" for row in output_rows),
        "rows": output_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output": str(args.output),
        "sha256": sha256(args.output),
        "rows": payload["expected_rows"],
        "quantity": payload["expected_quantity"],
        "catalog_rows": payload["expected_catalog_rows"],
        "hidden_legacy_rows": payload["expected_hidden_legacy_rows"],
        "unique_identities": payload["expected_unique_identities"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--old-variants", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-classification-sha256", required=True)
    parser.add_argument("--expected-old-variants-sha256", required=True)
    parser.add_argument("--expected-decisions-sha256", required=True)
    parser.add_argument("--expected-rows", type=int, default=173)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
