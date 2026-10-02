from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re

from fastapi import HTTPException


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_INVALID_SECRET_VALUES = frozenset({"", "change-me", "changeme", "secret", "test-token"})


@dataclass(frozen=True)
class OneCIntegrationIdentity:
    client_id: str
    credential_id: str
    legacy_shared: bool = False

    def audit_metadata(self) -> dict[str, str | bool]:
        return {
            "integration": "1c",
            "client_id": self.client_id,
            "credential_id": self.credential_id,
            "legacy_shared": self.legacy_shared,
        }


def _identifier(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be 1-64 characters using letters, numbers, '.', '_', or '-'")
    return normalized


def _secret_digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def parse_onec_client_credentials(
    raw: str,
    *,
    minimum_secret_length: int = 1,
) -> dict[str, dict[str, str]]:
    """Parse named 1C clients and rotation slots without logging credentials.

    The environment value is a JSON object shaped as
    ``{"client-id": {"credential-id": "secret"}}``. Multiple credential
    IDs allow an explicit overlap window during rotation. Removing the old
    credential from configuration ends that window without changing identity.
    """
    serialized = str(raw or "").strip()
    if not serialized:
        return {}
    try:
        payload = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValueError("INTEGRATION_1C_CLIENTS_JSON must be valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("INTEGRATION_1C_CLIENTS_JSON must be a non-empty object")

    clients: dict[str, dict[str, str]] = {}
    secret_owners: dict[bytes, tuple[str, str]] = {}
    for raw_client_id, raw_credentials in payload.items():
        client_id = _identifier(raw_client_id, "1C client id")
        if client_id in clients:
            raise ValueError(f"duplicate 1C client id: {client_id}")
        if not isinstance(raw_credentials, dict) or not raw_credentials:
            raise ValueError(f"1C client {client_id} must define at least one named credential")
        credentials: dict[str, str] = {}
        for raw_credential_id, raw_secret in raw_credentials.items():
            credential_id = _identifier(raw_credential_id, "1C credential id")
            if not isinstance(raw_secret, str):
                raise ValueError(f"1C credential {client_id}/{credential_id} must be a string")
            secret = raw_secret.strip()
            if len(secret) < minimum_secret_length or secret.casefold() in _INVALID_SECRET_VALUES:
                raise ValueError(
                    f"1C credential {client_id}/{credential_id} must be a unique high-entropy value"
                )
            digest = _secret_digest(secret)
            previous_owner = secret_owners.get(digest)
            if previous_owner is not None:
                raise ValueError(
                    "1C credentials must not be shared between clients or rotation slots "
                    f"({previous_owner[0]}/{previous_owner[1]} and {client_id}/{credential_id})"
                )
            secret_owners[digest] = (client_id, credential_id)
            credentials[credential_id] = secret
        clients[client_id] = credentials
    return clients


def authenticate_onec_integration(
    *,
    supplied_client_id: str | None,
    supplied_token: str | None,
    clients_json: str,
    legacy_shared_token: str,
    strict_security_required: bool,
) -> OneCIntegrationIdentity:
    clients = parse_onec_client_credentials(
        clients_json,
        minimum_secret_length=32 if strict_security_required else 1,
    )
    supplied_client = str(supplied_client_id or "").strip()
    token_digest = _secret_digest(str(supplied_token or ""))

    if clients:
        matched_credential: str | None = None
        # Compare every configured credential so an unknown client and a wrong
        # token follow the same authentication path and response.
        for client_id, credentials in sorted(clients.items()):
            for credential_id, expected in sorted(credentials.items()):
                token_matches = hmac.compare_digest(token_digest, _secret_digest(expected))
                if client_id == supplied_client and token_matches:
                    matched_credential = credential_id
        if matched_credential is None:
            raise HTTPException(401, "Invalid 1C token")
        return OneCIntegrationIdentity(supplied_client, matched_credential)

    expected = str(legacy_shared_token or "").strip()
    if strict_security_required:
        raise HTTPException(503, "1C per-client integration identity is not configured")
    if not expected:
        raise HTTPException(503, "1C integration token is not configured")
    if not hmac.compare_digest(token_digest, _secret_digest(expected)):
        raise HTTPException(401, "Invalid 1C token")
    return OneCIntegrationIdentity("legacy-shared", "legacy", legacy_shared=True)
