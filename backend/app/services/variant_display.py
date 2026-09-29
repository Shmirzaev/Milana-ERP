"""Presentation-only variant numbers; stored keys and scan payloads stay intact."""
import re


def format_variant_number(raw) -> str:
    value = str(raw).strip() if raw is not None else ""
    if not value or value in {"—", "-"}:
        return ""
    value = re.sub(r"^(?:V\s*[-=]\s*)+", "", value, flags=re.IGNORECASE).strip()
    return "V-" + value if value else ""


def format_model_variant_code(raw) -> str:
    code = str(raw).strip() if raw is not None else ""
    parts = re.fullmatch(r"(.+\d.*?)-((?:V\s*[-=]\s*)?\d[^\s]*)", code, flags=re.IGNORECASE)
    return f"{parts[1]}-{format_variant_number(parts[2])}" if parts else code
