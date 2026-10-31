from pathlib import Path

from app.core import security
from app.core.config import settings


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_PYTHON_JOSE_HS256_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJjb21wYXRpYmlsaXR5LXVzZXIiLCJmYWN0b3J5X2NvZGUiOiJNSUwiLCJpYXQiOjE3MDAwMDAwMDB9."
    "mrUJkV7dOMNzEAzDb2Q3XKItNrngAxhuyLb7ES8YAEk"
)
JWT_COMPATIBILITY_SECRET = "jwt-compatibility-secret-32-bytes-long"


def test_pyjwt_decodes_existing_python_jose_hs256_token(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", JWT_COMPATIBILITY_SECRET)
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")

    claims = security.decode_token(LEGACY_PYTHON_JOSE_HS256_TOKEN)

    assert claims == {
        "sub": "compatibility-user",
        "factory_code": "MIL",
        "iat": 1_700_000_000,
    }


def test_backend_manifest_removes_vulnerable_ecdsa_dependency_chain():
    requirements = (REPOSITORY_ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    normalized = requirements.casefold()

    assert "pyjwt==2.15.0" in normalized
    assert "python-jose" not in normalized
    assert "ecdsa" not in normalized


