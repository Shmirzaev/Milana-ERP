"""Read contract for global system preferences."""

from pydantic import BaseModel, ConfigDict, Field

from app.libs.enums.settings import SettingsLanguage


class SystemPreferencesOut(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    default_language: SettingsLanguage = SettingsLanguage.EN
    timezone: str = "UTC"
    model_types: list[str] = Field(default_factory=lambda: ["Dress", "Top", "Skirt", "Pants", "Outerwear"])
    require_material_reservation_before_cutting: bool = False
