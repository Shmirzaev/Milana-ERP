"""Stable reusable process identities; model-specific rates remain on the model."""
import unicodedata
import hashlib

SECTIONS = {"sewing", "cutting", "packaging", "cleaning", "pressing", "control", "storage", "tikuv", "transfer", "snaps", "buttons", "cord", "sorting"}
ALIASES = {"пошив": "sewing", "tikuv": "tikuv", "крой": "cutting", "kroy": "cutting",
           "упаковка": "packaging", "upakovka": "packaging", "чистка": "cleaning",
           "chistka": "cleaning", "глажка": "pressing", "dazmol": "pressing",
           "контроль": "control", "kontrol": "control", "nazorat": "control", "склад": "storage",
           "трансфер": "transfer", "кнопки": "snaps", "пуговицы": "buttons", "шнур": "cord", "тасниф": "sorting"}


def normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalized_key(value: str) -> str:
    """Bound the indexed identity without truncating Unicode process names."""
    return hashlib.sha256(normalized_name(value).encode("utf-8")).hexdigest()


def process_section(row: dict) -> str:
    source = normalized_name(str(row.get("sourceStage") or row.get("source_stage") or ""))
    section = normalized_name(str(row.get("section") or "sewing"))
    return source if source in SECTIONS else ALIASES.get(source, section if section in SECTIONS else ALIASES.get(section, "sewing"))
