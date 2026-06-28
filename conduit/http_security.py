import re

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)

_TOKEN_RE = re.compile(r"^(api|cli)-[A-Za-z0-9]{28}$")


class TokenGate:
    """ASGI middleware: Content-Type + token shape gate before the MCP handler.

    The SDK validator is built once at startup with DNS rebinding protection
    off (loopback mode). It still validates Content-Type on POST requests.
    Token presence is checked after the SDK validator; shape is checked next.
    Requests to /health bypass both checks.
    """

    def __init__(self, app):
        self.app = app
        self._sec = TransportSecurityMiddleware(
            TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
                allowed_origins=[],
                allowed_hosts=[],
            )
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return

        conn = HTTPConnection(scope)
        resp = await self._sec.validate_request(
            conn, is_post=scope["method"] == "POST"
        )
        if resp is not None:
            await resp(scope, receive, send)
            return

        token = conn.headers.get("x-phabricator-token")
        if not token:
            response = JSONResponse(
                {"error": "Missing X-Phabricator-Token header"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        if not _TOKEN_RE.match(token):
            response = JSONResponse(
                {"error": "Token must match ^(api|cli)-[A-Za-z0-9]{28}$"},
                status_code=400,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def register_health(mcp):
    """Register /health GET route on the given FastMCP instance."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request):
        return JSONResponse({"status": "ok"})
