import logging
import re

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)

# \Z (not $) so a trailing newline cannot sneak past the shape gate.
_TOKEN_RE = re.compile(r"^(api|cli)-[A-Za-z0-9]{28}\Z")

# Matches a Phorge conduit token anywhere in a string (no anchors), for
# redaction. {28,} (not {28}) so a token run with accidental trailing alnum is
# redacted whole rather than leaving a tail.
_TOKEN_SUBSTR_RE = re.compile(r"(api|cli)-[A-Za-z0-9]{28,}")

# A bare formatter to pre-render an exception/traceback so we can scrub it.
_EXC_FORMATTER = logging.Formatter()
_REDACTED = "[REDACTED-TOKEN]"


class TokenGate:
    """ASGI middleware: DNS-rebinding + token shape gate before the MCP handler.

    The SDK validator is built once at startup. In loopback mode (``public``
    False) DNS-rebinding protection is off, so an empty allowlist does not
    421 every request; Content-Type on POST is still validated. In public mode
    (``public`` True) protection is on and Origin/Host are checked against
    ``allowed_origins``/``allowed_hosts``.

    Token presence is checked after the validator (missing -> 401); shape is
    checked next (malformed -> 400). Requests to /health bypass both checks.
    """

    def __init__(self, app, *, public=False, allowed_origins=None, allowed_hosts=None):
        self.app = app
        self._sec = TransportSecurityMiddleware(
            TransportSecuritySettings(
                enable_dns_rebinding_protection=public,
                allowed_origins=allowed_origins or [],
                allowed_hosts=allowed_hosts or [],
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


def _redact(value):
    """Scrub a token from a log arg. Strings are substituted directly; a non-str
    arg (commonly an Exception passed as ``%s``) is rendered with ``str()`` and,
    if that rendering carries a token, replaced by the redacted rendering so the
    token cannot reach the formatted message."""
    if isinstance(value, str):
        return _TOKEN_SUBSTR_RE.sub(_REDACTED, value)
    try:
        rendered = str(value)
    except Exception:
        return value
    if _TOKEN_SUBSTR_RE.search(rendered):
        return _TOKEN_SUBSTR_RE.sub(_REDACTED, rendered)
    return value


class TokenRedactionFilter(logging.Filter):
    """Scrub Phorge conduit tokens from log records.

    Tokens have a fixed shape (``api-``/``cli-`` + 28+ chars), so a substring
    sub catches a token wherever it appears. The filter rewrites the message
    template, each positional/keyword arg (including a non-str arg whose
    ``str()`` carries a token, e.g. an Exception logged with ``%s``), and the
    exc_info traceback / stack_info: it pre-renders and scrubs the traceback
    into ``record.exc_text`` so the handler's formatter reuses the scrubbed
    text instead of re-rendering the raw one.
    """

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _TOKEN_SUBSTR_RE.sub(_REDACTED, record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact(v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact(a) for a in record.args)
        if record.exc_info and not record.exc_text:
            record.exc_text = _EXC_FORMATTER.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _TOKEN_SUBSTR_RE.sub(_REDACTED, record.exc_text)
        if record.stack_info:
            record.stack_info = _TOKEN_SUBSTR_RE.sub(_REDACTED, record.stack_info)
        return True


# Loggers that can plausibly carry an outbound token (request URLs, header
# dumps, tracebacks). Redaction is attached to each one directly and to the
# root handlers, so both records logged here and anything propagating to root
# are scrubbed.
_REDACTED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "conduit",
)


def install_token_redaction():
    """Attach a TokenRedactionFilter at the points that together cover every
    record. The root *handler* filters scrub records propagated up from any
    logger (propagation runs ancestor handlers, not ancestor filters), which is
    the catch-all. The named-logger filters scrub records emitted directly on
    those loggers even if they have their own non-propagating handlers. The root
    logger filter covers logs emitted directly on root. Returns the filter so
    tests can detach it."""
    f = TokenRedactionFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for handler in root.handlers:
        handler.addFilter(f)
    for name in _REDACTED_LOGGERS:
        logging.getLogger(name).addFilter(f)
    return f


def register_health(mcp):
    """Register /health GET route on the given FastMCP instance."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request):
        return JSONResponse({"status": "ok"})
