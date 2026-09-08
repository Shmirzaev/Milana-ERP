"""Security headers for self-contained, server-rendered warehouse print pages."""
from base64 import b64encode
from hashlib import sha256

from fastapi.responses import HTMLResponse


def warehouse_print_response(document: str) -> HTMLResponse:
    # Allow only the fixed print button's handler, never arbitrary inline scripts.
    print_hash = b64encode(sha256(b"window.print()").digest()).decode("ascii")
    policy = (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        f"script-src 'unsafe-hashes' 'sha256-{print_hash}'; "
        "script-src-elem 'none'; "
        "img-src 'self' data: blob:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    return HTMLResponse(document, headers={
        "Content-Security-Policy": policy,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })
