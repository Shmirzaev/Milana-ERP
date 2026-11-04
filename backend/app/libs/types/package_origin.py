from typing import TypedDict

from app.libs.enums.production import SewingFactoryCode


class PackageNumbers(TypedDict):
    model_no: str | None
    variant_no: str | None


class PackageSewingOrigin(TypedDict):
    sewing_factory_code: SewingFactoryCode | None
    sewing_factory_codes: list[SewingFactoryCode]
