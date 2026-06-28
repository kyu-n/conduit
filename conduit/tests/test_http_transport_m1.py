"""M1 Streamable HTTP transport tests: TokenGate, shared-client lifespan,
loopback guard, proxy/cert/UA wiring, json_response, and get_client behaviour."""

import os
from unittest import mock

import httpx
import pytest
from starlette.middleware import Middleware

from conduit.client.base import DEFAULT_USER_AGENT
from conduit.conduit import ConduitApp, PhabricatorConfig, _TOKEN_RE
from conduit.http_security import TokenGate, register_health

VALID_API = "api-" + "a" * 28
VALID_CLI = "cli-" + "b" * 28
BAD_PREFIX = "tok-" + "x" * 28  # wrong prefix
BAD_SHORT = "api-" + "x" * 20  # too short


@pytest.fixture(autouse=True)
def phabricator_env():
    # Save originals so we restore them exactly (not clobber suite-level env).
    saved = {
        k: os.environ.get(k)
        for k in (
            "PHABRICATOR_URL",
            "PHABRICATOR_TOKEN",
            "PHABRICATOR_PROXY",
            "PHABRICATOR_DISABLE_CERT_VERIFY",
            "PHABRICATOR_USER_AGENT",
        )
    }
    os.environ["PHABRICATOR_URL"] = "http://127.0.0.1:8080/api/"
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


@pytest.fixture
def conduit_app():
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    register_health(app.mcp)
    return app


@pytest.fixture
def starlette_app(conduit_app):
    return conduit_app.mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        middleware=[Middleware(TokenGate)],
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


async def test_health_no_token(starlette_app):
    """/health returns 200 without any token."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_foreign_origin_passes(starlette_app):
    """/health bypasses origin/token checks; a foreign Origin header is ignored."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.get("/health", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TokenGate: token presence and shape
# ---------------------------------------------------------------------------


async def test_no_token_returns_401(starlette_app):
    transport = httpx.ASGITransport(app=starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            }},
        )
    assert resp.status_code == 401
    body = resp.json()
    # Response names the header
    assert "X-Phabricator-Token" in body.get("error", "")


async def test_bad_prefix_returns_400(starlette_app):
    transport = httpx.ASGITransport(app=starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            }},
            headers={"x-phabricator-token": BAD_PREFIX},
        )
    assert resp.status_code == 400


async def test_bad_short_token_returns_400(starlette_app):
    transport = httpx.ASGITransport(app=starlette_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            }},
            headers={"x-phabricator-token": BAD_SHORT},
        )
    assert resp.status_code == 400


async def test_valid_api_token_passes_gate(starlette_app):
    """A well-formed api- token passes TokenGate and reaches the MCP layer."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with starlette_app.lifespan(starlette_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                }},
                headers={"x-phabricator-token": VALID_API},
            )
    # TokenGate accepted the token; any non-401/400 means the gate passed.
    assert resp.status_code not in (400, 401)


async def test_valid_cli_token_passes_gate(starlette_app):
    """A well-formed cli- token also passes TokenGate."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with starlette_app.lifespan(starlette_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                }},
                headers={"x-phabricator-token": VALID_CLI},
            )
    assert resp.status_code not in (400, 401)


async def test_loopback_post_not_421(starlette_app):
    """Loopback mode (enable=False) does not block with 421."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with starlette_app.lifespan(starlette_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                }},
                headers={
                    "x-phabricator-token": VALID_API,
                    "host": "localhost:8000",
                },
            )
    assert resp.status_code != 421


# ---------------------------------------------------------------------------
# Shared-client lifespan and reuse
# ---------------------------------------------------------------------------


async def test_shared_client_built_during_lifespan(conduit_app, starlette_app):
    """_shared_client is None before lifespan and non-None during it."""
    assert conduit_app._shared_client is None
    async with starlette_app.lifespan(starlette_app):
        assert conduit_app._shared_client is not None
        assert not conduit_app._shared_client.is_closed


async def test_shared_client_closed_after_lifespan(conduit_app, starlette_app):
    """_shared_client is closed after lifespan exits."""
    async with starlette_app.lifespan(starlette_app):
        shared = conduit_app._shared_client
    assert shared.is_closed


async def test_get_client_before_lifespan_raises(conduit_app):
    """get_client() raises when called before lifespan has started."""
    with mock.patch(
        "conduit.conduit.get_http_headers",
        return_value={"x-phabricator-token": VALID_API},
    ):
        with pytest.raises(RuntimeError, match="lifespan"):
            conduit_app.get_client()


async def test_wrappers_share_same_http_client(conduit_app, starlette_app):
    """Two get_client() calls return wrappers that share the same httpx.Client."""
    async with starlette_app.lifespan(starlette_app):
        with mock.patch("conduit.conduit.get_http_headers") as mh:
            mh.return_value = {"x-phabricator-token": VALID_API}
            client_a = conduit_app.get_client()

            mh.return_value = {"x-phabricator-token": VALID_CLI}
            client_b = conduit_app.get_client()

        # Same pool, different wrappers
        assert client_a.http_client is conduit_app._shared_client
        assert client_b.http_client is conduit_app._shared_client
        assert client_a is not client_b

        # Each sends its own token
        assert client_a.maniphest.api_token == VALID_API
        assert client_b.maniphest.api_token == VALID_CLI


async def test_wrapper_close_does_not_close_shared_client(conduit_app, starlette_app):
    """close() on a wrapper returned by get_client() does NOT close the shared client."""
    async with starlette_app.lifespan(starlette_app):
        with mock.patch(
            "conduit.conduit.get_http_headers",
            return_value={"x-phabricator-token": VALID_API},
        ):
            wrapper = conduit_app.get_client()
        wrapper.close()
        assert not conduit_app._shared_client.is_closed


# ---------------------------------------------------------------------------
# proxy / cert / UA constructor spy
# ---------------------------------------------------------------------------


async def test_proxy_cert_ua_reach_httpx_client(starlette_app):
    """proxy= and verify= from config reach the httpx.Client constructor."""
    os.environ["PHABRICATOR_PROXY"] = "http://proxy.example.com"
    os.environ["PHABRICATOR_DISABLE_CERT_VERIFY"] = "1"
    os.environ["PHABRICATOR_USER_AGENT"] = "TestAgent/1.0"

    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    register_health(app.mcp)
    sa = app.mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        middleware=[Middleware(TokenGate)],
    )

    with mock.patch("conduit.conduit.httpx.Client") as mock_client:
        mock_instance = mock.MagicMock()
        mock_client.return_value = mock_instance

        async with sa.lifespan(sa):
            pass

    mock_client.assert_called_once()
    call_kwargs = mock_client.call_args.kwargs
    assert call_kwargs.get("proxy") == "http://proxy.example.com"
    assert call_kwargs.get("verify") is False
    headers = call_kwargs.get("headers", {})
    assert headers.get("User-Agent") == "TestAgent/1.0"


async def test_default_ua_used_when_not_set(starlette_app):
    """Default User-Agent is used when PHABRICATOR_USER_AGENT is not set."""
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    register_health(app.mcp)
    sa = app.mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        middleware=[Middleware(TokenGate)],
    )

    with mock.patch("conduit.conduit.httpx.Client") as mock_client:
        mock_instance = mock.MagicMock()
        mock_client.return_value = mock_instance

        async with sa.lifespan(sa):
            pass

    call_kwargs = mock_client.call_args.kwargs
    headers = call_kwargs.get("headers", {})
    assert headers.get("User-Agent") == DEFAULT_USER_AGENT


# ---------------------------------------------------------------------------
# json_response -> Content-Type: application/json
# ---------------------------------------------------------------------------


async def test_json_response_content_type(starlette_app):
    """json_response=True causes the MCP endpoint to respond with application/json."""
    transport = httpx.ASGITransport(app=starlette_app)
    async with starlette_app.lifespan(starlette_app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            resp = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                }},
                headers={"x-phabricator-token": VALID_API},
            )
    assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Loopback guard
# ---------------------------------------------------------------------------


def test_loopback_guard_refuses_00000(conduit_app):
    """0.0.0.0 is rejected by the M1 loopback guard."""
    with pytest.raises(ValueError, match="Non-loopback"):
        conduit_app.run_http_mode("0.0.0.0", 8000, "/mcp")


def test_loopback_guard_refuses_any_ipv6(conduit_app):
    """:: (any IPv6) is rejected."""
    with pytest.raises(ValueError, match="Non-loopback"):
        conduit_app.run_http_mode("::", 8000, "/mcp")


def test_loopback_guard_refuses_routable_ip(conduit_app):
    """A routable IP is rejected."""
    with pytest.raises(ValueError, match="Non-loopback"):
        conduit_app.run_http_mode("192.168.1.1", 8000, "/mcp")


def test_loopback_guard_refuses_public_ip(conduit_app):
    """A public IP is rejected."""
    with pytest.raises(ValueError, match="Non-loopback"):
        conduit_app.run_http_mode("8.8.8.8", 8000, "/mcp")


def test_loopback_guard_accepts_127001(conduit_app):
    """127.0.0.1 is accepted (loopback)."""
    # run_http_mode calls mcp.run() which blocks; patch it out.
    with mock.patch.object(conduit_app.mcp, "run"):
        # Should not raise
        conduit_app.run_http_mode("127.0.0.1", 8000, "/mcp")


def test_loopback_guard_accepts_localhost(conduit_app):
    """The literal 'localhost' is accepted."""
    with mock.patch.object(conduit_app.mcp, "run"):
        conduit_app.run_http_mode("localhost", 8000, "/mcp")


# ---------------------------------------------------------------------------
# PhabricatorConfig http_mode token handling
# ---------------------------------------------------------------------------


def test_http_mode_config_nulls_token():
    """PhabricatorConfig(http_mode=True) sets token=None even when env is set."""
    os.environ["PHABRICATOR_TOKEN"] = VALID_API
    try:
        config = PhabricatorConfig(http_mode=True)
        assert config.token is None
    finally:
        del os.environ["PHABRICATOR_TOKEN"]


# ---------------------------------------------------------------------------
# Token regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        (VALID_API, True),
        (VALID_CLI, True),
        ("api-" + "Z" * 28, True),         # uppercase alnum
        ("api-" + "A1b2C3" * 4 + "EfGh", True),  # mixed, exactly 28 chars after prefix
        (BAD_PREFIX, False),                # wrong prefix
        (BAD_SHORT, False),                 # too short
        ("api-" + "x" * 29, False),         # too long
        ("api-" + "x" * 27 + "!", False),   # non-alnum char
        ("", False),
        ("api-", False),
    ],
)
def test_token_regex(token, expected):
    assert bool(_TOKEN_RE.match(token)) == expected
