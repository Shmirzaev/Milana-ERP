"""Partial update contract for global company information."""

from pydantic import BaseModel, ConfigDict, EmailStr


class CompanyInfoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The default is omitted by model_dump(exclude_unset=True); an explicit null
    # remains invalid as in the legacy full-section model.
    name: str = "Milana Ecosystem"
    logo_url: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
