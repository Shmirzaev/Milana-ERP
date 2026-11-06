"""Stable reusable process identities; model-specific rates remain on the model."""
import unicodedata
import hashlib

from app.libs.enums.catalog import PAID_PROCESS_SECTION_VALUES, PaidProcessSection

# Compatibility symbol for the canonical paid-process section vocabulary.
SECTIONS = PAID_PROCESS_SECTION_VALUES
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


def _text(value) -> str:
    """Raw string value; a section member must not stringify as 'Class.MEMBER'."""
    if isinstance(value, PaidProcessSection):
        return value.value
    return str(value or "")


def process_section(row: dict) -> str:
    """Legacy raw-input boundary: raw seed text in, legacy section string out.

    This interprets historical source records, so its canonical output stays the
    legacy section *string*. It does not adopt the `PaidProcessSection` contract:
    the enum-backed canonical boundary is the paid-process DTO and the mapped
    write, not this legacy interpreter. The membership set below only carries
    the canonical values as plain strings so the list is not duplicated.
    """
    source = normalized_name(_text(row.get("sourceStage") or row.get("source_stage")))
    section = normalized_name(_text(row.get("section") or PaidProcessSection.SEWING.value))
    return source if source in SECTIONS else ALIASES.get(source, section if section in SECTIONS else ALIASES.get(section, PaidProcessSection.SEWING.value))
