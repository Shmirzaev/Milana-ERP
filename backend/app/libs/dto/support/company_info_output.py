"""Read contract for global company information."""

from pydantic import BaseModel, ConfigDict, EmailStr


class CompanyInfoOut(BaseModel):
    # Ignore legacy stored extension keys as the route's prior Pydantic model did.
    model_config = ConfigDict(extra="ignore")

    name: str = "Milana Ecosystem"
    logo_url: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
