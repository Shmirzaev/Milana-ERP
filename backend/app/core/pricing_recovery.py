"""Fail-closed legacy pricing routes in the schema0156 production recovery image."""
from starlette.responses import JSONResponse


class PricingRecoveryUnavailable:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        prefix = "/api/price-calculation"
        if scope["type"] == "http" and (path == prefix or path.startswith(prefix + "/")):
            response = JSONResponse(
                {"detail": "Pricing is temporarily unavailable. Please contact Finance."},
                status_code=503, headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
