from pydantic import BaseModel, Field, field_validator


class DeviceIn(BaseModel):
    device_key: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Main turnstile", min_length=1, max_length=128)
    vendor: str = Field(default="Hikvision", min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    serial_no: str | None = Field(default=None, max_length=128)
    source_host: str | None = Field(default=None, max_length=255)
    reported_person_count: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("device_key")
    @classmethod
    def validate_device_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("-", "").replace("_", "").isalnum():
            raise ValueError("device_key may contain only letters, numbers, hyphens, and underscores")
        return normalized


class ManagedDeviceIn(BaseModel):
    device_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    vendor: str = Field(pattern="^(Hikvision|Dahua)$")
    source_host: str = Field(min_length=8, max_length=255)
    certificate_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("device_key")
    @classmethod
    def validate_managed_device_key(cls, value: str) -> str:
        return DeviceIn.validate_device_key(value)

    @field_validator("source_host")
    @classmethod
    def validate_source_host(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.lower().startswith("https://"):
            raise ValueError("Attendance device URL must use HTTPS")
        return normalized

    @field_validator("certificate_sha256")
    @classmethod
    def validate_certificate_sha256(cls, value: str) -> str:
        normalized = "".join(character for character in value.lower() if character in "0123456789abcdef")
        if len(normalized) != 64:
            raise ValueError("Certificate SHA-256 must contain 64 hexadecimal characters")
        return normalized


class ManagedDeviceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    sync_enabled: bool | None = None


