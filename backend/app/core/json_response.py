"""Encode large, unmodelled read responses in their synchronous request thread."""

from functools import wraps
from inspect import iscoroutinefunction
from typing import Callable

from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse


def json_response_endpoint(endpoint: Callable[..., object]) -> Callable[..., JSONResponse]:
    """Register a sync endpoint without moving its JSON work onto the ASGI loop.

    Use only for endpoints without a response model. Keep the original callable
    for service-level callers; the registered wrapper uses FastAPI's existing
    encoder and Starlette's existing renderer, including datetime/Decimal rules.
    """
    if iscoroutinefunction(endpoint):
        raise TypeError("JSON response encoding requires a synchronous endpoint")

    @wraps(endpoint)
    def response(*args, **kwargs):
        return JSONResponse(content=jsonable_encoder(endpoint(*args, **kwargs)))

    return response
