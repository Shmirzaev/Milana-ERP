import pytest
from pydantic import ValidationError

from app.schemas.waste import WasteIn


@pytest.mark.parametrize(("field", "maximum"), [("waste_type", 64), ("unit", 32)])
def test_waste_record_strings_match_storage_width(field, maximum):
    accepted_payload = {"waste_type": "scrap", "quantity": "1", "unit": "kg"}
    accepted_payload[field] = "x" * maximum
    rejected_payload = {**accepted_payload, field: "x" * (maximum + 1)}
    accepted = WasteIn(**accepted_payload)

    assert getattr(accepted, field) == "x" * maximum
    with pytest.raises(ValidationError):
        WasteIn(**rejected_payload)
