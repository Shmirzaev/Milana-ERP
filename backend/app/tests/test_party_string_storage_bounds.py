import pytest
from pydantic import ValidationError

from app.schemas.catalog import PartyIn


@pytest.mark.parametrize(("field", "maximum"), [
    ("name", 255),
    ("phone", 64),
    ("email", 255),
])
def test_party_string_fields_match_storage_width(field, maximum):
    accepted_payload = {"name": "Party", field: "x" * maximum}
    rejected_payload = {"name": "Party", field: "x" * (maximum + 1)}
    accepted = PartyIn(**accepted_payload)

    assert getattr(accepted, field) == "x" * maximum
    with pytest.raises(ValidationError):
        PartyIn(**rejected_payload)
