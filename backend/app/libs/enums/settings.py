"""Fixed discriminators and language values for global settings."""

from enum import Enum


class SettingsSection(str, Enum):
    COMPANY_INFO = "company_info"
    FINANCIAL = "financial"
    PREFERENCES = "preferences"


class SettingsLanguage(str, Enum):
    EN = "en"
    RU = "ru"
    UZ = "uz"
