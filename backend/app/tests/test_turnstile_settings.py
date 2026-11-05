import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.libs.enums.turnstile import GateMode

def test_disabled_default_is_canonical_enum(monkeypatch):
    monkeypatch.delenv("TURNSTILE_PROVISIONING_MODE", raising=False)
    assert Settings(_env_file=None).TURNSTILE_PROVISIONING_MODE is GateMode.DISABLED

@pytest.mark.parametrize("environment", ["prod", "production", "staging"])
def test_private_simulator_is_forbidden_in_production(environment):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENV=environment, TURNSTILE_PROVISIONING_MODE="simulator")

def test_public_marker_cannot_enable_simulator(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "1")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENV="development", TURNSTILE_PROVISIONING_MODE="simulator")

@pytest.mark.parametrize("values", [
    {"TURNSTILE_PROVISIONING_MODE":"live"},
    {"TURNSTILE_SIMULATOR_MAX_ATTEMPTS":0},
    {"TURNSTILE_SIMULATOR_MAX_ATTEMPTS":11},
    {"TURNSTILE_SIMULATOR_LEASE_SECONDS":0},
    {"TURNSTILE_PHOTO_MAX_PIXELS":50_000_001},
])
def test_unsupported_mode_and_unbounded_limits_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
