import os
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send


AUTH_REQUEST_MAX_BYTES_ENV = "AUTH_REQUEST_MAX_BYTES"
DEFAULT_AUTH_REQUEST_MAX_BYTES = 64 * 1024

_JSON_AUTH_PATHS = {
    "/api/auth/forgot-password",
    "/api/auth/login-json",
    "/api/auth/reset-password",
    "/api/session/forgot-password",
    "/api/session/login-json",
    "/api/session/reset-password",
}
_FORM_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/token",
    "/api/session/login",
}


def auth_request_max_bytes() -> int:
    raw_value = os.environ.get(AUTH_REQUEST_MAX_BYTES_ENV, "").strip()
    if not raw_value:
        return DEFAULT_AUTH_REQUEST_MAX_BYTES
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{AUTH_REQUEST_MAX_BYTES_ENV} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{AUTH_REQUEST_MAX_BYTES_ENV} must be a positive integer")
    return value


def validate_request_body_runtime_configuration() -> None:
    auth_request_max_bytes()


def _content_type(headers: list[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() == b"content-type":
            return value.decode("latin-1").split(";", 1)[0].strip().lower()
    return ""


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    values = [value for name, value in headers if name.lower() == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("multiple content lengths")
    value = int(values[0].decode("ascii"))
    if value < 0:
        raise ValueError("negative content length")
    return value


def _is_bounded_auth_request(scope: Scope) -> bool:
    if scope.get("type") != "http" or str(scope.get("method", "")).upper() not in {"POST", "PUT", "PATCH"}:
        return False
    path = str(scope.get("path", "")).rstrip("/") or "/"
    content_type = _content_type(scope.get("headers", []))
    return (
        path in _JSON_AUTH_PATHS and content_type == "application/json"
    ) or (
        path in _FORM_AUTH_PATHS
        and content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}
    )


class AuthRequestBodyLimitMiddleware:
    """Stream-count public credential bodies without touching uploads.

    The allowlist intentionally excludes authenticated state-changing routes,
    application upload routes, and arbitrary JSON.  Multipart is bounded only
    on public login/token routes, where it carries form fields rather than
    files, so upload streaming and existing auth/validation precedence remain
    intact.
    """

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_bounded_auth_request(scope):
            await self.app(scope, receive, send)
            return

        limit = auth_request_max_bytes()
        try:
            declared_length = _content_length(scope.get("headers", []))
        except (UnicodeDecodeError, ValueError):
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            return
        if declared_length is not None and declared_length > limit:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            return

        consumed = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal consumed, exceeded
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    exceeded = True
                    # Stop parser/route execution without buffering or reading
                    # the rest of an unbounded client stream.  FastAPI may turn
                    # this disconnect into its generic 400; limited_send
                    # suppresses that response and emits the authoritative 413.
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
