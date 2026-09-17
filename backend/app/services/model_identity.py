from app.models import Model


def model_number_fields(model: Model | None) -> dict[str, str | None]:
    """Business model/variant numbers, respecting explicitly configured base models."""
    if not model:
        return {"model_no": None, "variant_no": None}
    code = str(model.code or "").strip()
    code_model, separator, code_variant = code.rpartition("-")
    if not separator or not code_model or not code_variant:
        code_model, code_variant = code, ""
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    configured_model = str(general.get("model_no") or general.get("modelNo") or "").strip()
    configured_variant = str(general.get("variant_no") or general.get("variantNo") or "").strip()
    return {
        "model_no": configured_model or code_model or None,
        "variant_no": (configured_variant if configured_model else configured_variant or code_variant) or None,
    }
