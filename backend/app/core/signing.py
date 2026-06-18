"""HMAC-signed, expiring URLs for otherwise-unauthenticated storage paths.

Sensitive uploaded files (e.g. sales-order printing attachments) are rendered in
the browser via <img> tags, which cannot attach an Authorization header. Instead
of serving them publicly, we hand out short-lived signed URLs:

    /storage/sales-order-files/<name>?exp=<unix-ts>&sig=<hmac-sha256>

The signature is computed over the bare path + expiry with the app's dedicated file-signing secret,
so only the server can mint a working link and it stops working after `exp`.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from app.core.config import settings

DEFAULT_TTL_SECONDS = 6 * 60 * 60  # 6h — generous enough for a long-lived page.


def _key() -> bytes:
    return settings.active_file_signing_secret.encode("utf-8")


def _signature(bare_path: str, exp: int) -> str:
    msg = f"{bare_path}:{exp}".encode("utf-8")
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()


def strip_signature(path: str | None) -> str | None:
    """Drop any existing query string so we always store/sign the bare path."""
    if not path:
        return path
    return path.split("?", 1)[0]


def sign_path(path: str | None, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str | None:
    if not path:
        return path
    bare = path.split("?", 1)[0]
    exp = int(time.time()) + int(ttl_seconds)
    sig = _signature(bare, exp)
    return f"{bare}?{urlencode({'exp': exp, 'sig': sig})}"


def verify_path(bare_path: str, exp: str | int | None, sig: str | None) -> bool:
    if not sig or exp is None:
        return False
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_int < int(time.time()):
        return False
    expected = _signature(bare_path.split("?", 1)[0], exp_int)
    return hmac.compare_digest(expected, str(sig))
