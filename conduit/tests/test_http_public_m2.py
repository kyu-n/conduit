"""M2 public-surface tests: CONDUIT_ALLOW_PUBLIC bind guard + allowlists,
CONDUIT_READONLY tool pruning, the public DNS-rebinding validator (Origin/Host),
and structural token redaction."""

import logging
import os
import sys
from unittest import mock

import httpx
import pytest
from starlette.middleware import Middleware

from conduit.conduit import ConduitApp, PhabricatorConfig
from conduit.http_security import (
    TokenGate,
    TokenRedactionFilter,
    _TOKEN_RE,
    install_token_redaction,
    register_health,
)

VALID_API = "api-" + "a" * 28
VALID_CLI = "cli-" + "b" * 28

_M2_ENV = (
    "PHABRICATOR_URL",
    "PHABRICATOR_TOKEN",
    "CONDUIT_ALLOW_PUBLIC",
    "CONDUIT_ALLOWED_HOSTS",
    "CONDUIT_ALLOWED_ORIGINS",
    "CONDUIT_READONLY",
)

# The 12 write tools that must vanish under read-only mode.
WRITE_TOOLS = {
    "pha_task_create",
    "pha_task_update",
    "pha_task_add_comment",
    "pha_task_update_relationships",
    "pha_repository_create",
    "pha_diff_create_from_content",
    "pha_diff_create",
    "pha_diff_add_comment",
    "pha_diff_update",
    "pha_project_create",
    "pha_project_update",
    "pha_workboard_move_task",
}


@pytest.fixture(autouse=True)
def clean_env():
    saved = {k: os.environ.get(k) for k in _M2_ENV}
    for k in _M2_ENV:
        os.environ.pop(k, None)
    os.environ["PHABRICATOR_URL"] = "http://127.0.0.1:8080/api/"
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def _build_app(public=False, hosts=None, origins=None):
    """A public starlette app whose TokenGate matches run_http_mode wiring."""
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    register_health(app.mcp)
    sa = app.mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        middleware=[
            Middleware(
                TokenGate,
                public=public,
                allowed_origins=origins or [],
                allowed_hosts=hosts or [],
            )
        ],
    )
    return app, sa


def _init_body():
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": 1,
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_config_defaults_private_and_writable():
    cfg = PhabricatorConfig(http_mode=True)
    assert cfg.allow_public is False
    assert cfg.allowed_hosts == []
    assert cfg.allowed_origins == []
    assert cfg.readonly is False


def test_config_allow_public_and_allowlists_parse():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_ALLOWED_HOSTS"] = "mcp.example.com, alt.example.com"
    os.environ["CONDUIT_ALLOWED_ORIGINS"] = "https://mcp.example.com"
    cfg = PhabricatorConfig(http_mode=True)
    assert cfg.allow_public is True
    assert cfg.allowed_hosts == ["mcp.example.com", "alt.example.com"]
    assert cfg.allowed_origins == ["https://mcp.example.com"]


def test_readonly_defaults_on_when_public():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    assert PhabricatorConfig(http_mode=True).readonly is True


def test_readonly_explicit_overrides_public_default():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_READONLY"] = "0"
    assert PhabricatorConfig(http_mode=True).readonly is False


def test_readonly_explicit_on_without_public():
    os.environ["CONDUIT_READONLY"] = "1"
    cfg = PhabricatorConfig(http_mode=True)
    assert cfg.allow_public is False
    assert cfg.readonly is True


@pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", " off "])
def test_readonly_falsey_words_disable(val):
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_READONLY"] = val
    assert PhabricatorConfig(http_mode=True).readonly is False


@pytest.mark.parametrize("val", ["1", "true", "YES", "on", " On "])
def test_readonly_truthy_words_enable(val):
    os.environ["CONDUIT_READONLY"] = val
    assert PhabricatorConfig(http_mode=True).readonly is True


@pytest.mark.parametrize("val", ["", "maybe", "of", "readonly", "2"])
def test_readonly_unrecognized_value_fails_closed(val):
    """A typo must raise, never silently expose write tools (fail closed)."""
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_READONLY"] = val
    with pytest.raises(ValueError, match="CONDUIT_READONLY"):
        PhabricatorConfig(http_mode=True)


def test_allow_public_unrecognized_value_raises():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "maybe"
    with pytest.raises(ValueError, match="CONDUIT_ALLOW_PUBLIC"):
        PhabricatorConfig(http_mode=True)


# ---------------------------------------------------------------------------
# CONDUIT_READONLY tool pruning (two-sided enumeration)
# ---------------------------------------------------------------------------


async def _tool_names(app):
    return {t.name for t in await app.mcp.list_tools()}


async def test_readonly_off_exposes_write_tools():
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    names = await _tool_names(app)
    assert WRITE_TOOLS <= names
    assert "conduit_guide" in names
    assert len(names) == 36


async def test_readonly_on_drops_every_write_tool():
    os.environ["CONDUIT_READONLY"] = "1"
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    names = await _tool_names(app)
    assert not (WRITE_TOOLS & names), WRITE_TOOLS & names
    # read tools and the guide survive
    assert "pha_task_get" in names
    assert "conduit_guide" in names
    assert len(names) == 24


async def test_readonly_default_on_under_allow_public():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    names = await _tool_names(app)
    assert not (WRITE_TOOLS & names)
    assert len(names) == 24


async def test_readonly_filter_keeps_prompt_passthrough():
    """The wrapper still registers the tackle prompt (a non-tool attribute)."""
    os.environ["CONDUIT_READONLY"] = "1"
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    names = {p.name for p in await app.mcp.list_prompts()}
    assert "tackle" in names


# ---------------------------------------------------------------------------
# run_http_mode public bind guard
# ---------------------------------------------------------------------------


def _app():
    config = PhabricatorConfig(http_mode=True)
    app = ConduitApp(config, http_mode=True)
    app.register_tools()
    return app


def test_public_bind_refused_without_allow_public():
    with pytest.raises(ValueError, match="Non-loopback"):
        _app().run_http_mode("0.0.0.0", 8000, "/mcp")


def test_public_refuses_empty_hosts():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_ALLOWED_ORIGINS"] = "https://mcp.example.com"
    with pytest.raises(ValueError, match="CONDUIT_ALLOWED_HOSTS"):
        _app().run_http_mode("0.0.0.0", 8000, "/mcp")


def test_public_refuses_empty_origins():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_ALLOWED_HOSTS"] = "mcp.example.com"
    with pytest.raises(ValueError, match="CONDUIT_ALLOWED_ORIGINS"):
        _app().run_http_mode("0.0.0.0", 8000, "/mcp")


def test_public_bind_runs_with_allowlists():
    os.environ["CONDUIT_ALLOW_PUBLIC"] = "1"
    os.environ["CONDUIT_ALLOWED_HOSTS"] = "mcp.example.com"
    os.environ["CONDUIT_ALLOWED_ORIGINS"] = "https://mcp.example.com"
    app = _app()
    captured = {}
    with mock.patch.object(app.mcp, "run", side_effect=lambda **kw: captured.update(kw)):
        app.run_http_mode("0.0.0.0", 8000, "/mcp")
    gate = captured["middleware"][0]
    assert gate.kwargs["public"] is True
    assert gate.kwargs["allowed_hosts"] == ["mcp.example.com"]
    assert gate.kwargs["allowed_origins"] == ["https://mcp.example.com"]


def test_loopback_bind_runs_private():
    app = _app()
    captured = {}
    with mock.patch.object(app.mcp, "run", side_effect=lambda **kw: captured.update(kw)):
        app.run_http_mode("127.0.0.1", 8000, "/mcp")
    assert captured["middleware"][0].kwargs["public"] is False


def test_path_health_collision_refused():
    """--path /health would alias the unauthenticated bypass; refuse to start."""
    app = _app()
    with mock.patch.object(app.mcp, "run"):
        with pytest.raises(ValueError, match="/health"):
            app.run_http_mode("127.0.0.1", 8000, "/health")


# ---------------------------------------------------------------------------
# Public DNS-rebinding validator (Origin / Host) end to end
# ---------------------------------------------------------------------------


async def test_public_foreign_origin_403():
    _, sa = _build_app(
        public=True,
        hosts=["mcp.example.com"],
        origins=["https://mcp.example.com"],
    )
    transport = httpx.ASGITransport(app=sa)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json=_init_body(),
            headers={
                "host": "mcp.example.com",
                "origin": "https://evil.example.com",
                "content-type": "application/json",
                "x-phabricator-token": VALID_API,
            },
        )
    assert resp.status_code == 403


async def test_public_bad_host_421():
    _, sa = _build_app(
        public=True,
        hosts=["mcp.example.com"],
        origins=["https://mcp.example.com"],
    )
    transport = httpx.ASGITransport(app=sa)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json=_init_body(),
            headers={
                "host": "evil.example.com",
                "content-type": "application/json",
                "x-phabricator-token": VALID_API,
            },
        )
    assert resp.status_code == 421


async def test_public_allowed_host_no_origin_passes():
    """A non-browser client (allowed Host, no Origin) reaches the MCP layer."""
    _, sa = _build_app(
        public=True,
        hosts=["mcp.example.com"],
        origins=["https://mcp.example.com"],
    )
    transport = httpx.ASGITransport(app=sa)
    async with sa.lifespan(sa):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            resp = await c.post(
                "/mcp",
                json=_init_body(),
                headers={
                    "host": "mcp.example.com",
                    "content-type": "application/json",
                    "accept": "application/json",
                    "x-phabricator-token": VALID_API,
                },
            )
    assert resp.status_code == 200


async def test_public_missing_token_still_401():
    _, sa = _build_app(
        public=True,
        hosts=["mcp.example.com"],
        origins=["https://mcp.example.com"],
    )
    transport = httpx.ASGITransport(app=sa)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post(
            "/mcp",
            json=_init_body(),
            headers={"host": "mcp.example.com", "content-type": "application/json"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Structural token redaction
# ---------------------------------------------------------------------------


def _remove_filter(f):
    root = logging.getLogger()
    root.removeFilter(f)
    for h in root.handlers:
        h.removeFilter(f)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore",
                 "conduit"):
        logging.getLogger(name).removeFilter(f)


def test_redaction_filter_scrubs_token_in_message():
    f = TokenRedactionFilter()
    rec = logging.LogRecord(
        "httpx", logging.DEBUG, __file__, 1,
        "POST /api/ token=api-ibsfhy4pjyxyq6vqnmopklhbay3d done", None, None,
    )
    f.filter(rec)
    assert "api-ibsfhy4pjyxyq6vqnmopklhbay3d" not in rec.getMessage()
    assert "[REDACTED-TOKEN]" in rec.getMessage()


def test_redaction_filter_scrubs_token_in_args():
    f = TokenRedactionFilter()
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        "request with %s", (VALID_CLI,), None,
    )
    f.filter(rec)
    assert VALID_CLI not in rec.getMessage()
    assert "[REDACTED-TOKEN]" in rec.getMessage()


def test_redaction_filter_scrubs_exception_arg():
    """An Exception logged with %s (the handlers.py idiom) is scrubbed."""
    f = TokenRedactionFilter()
    exc = RuntimeError("backend said: " + VALID_API)
    rec = logging.LogRecord(
        "conduit", logging.WARNING, __file__, 1,
        "tool %s failed: %s", ("pha_task_get", exc), None,
    )
    f.filter(rec)
    assert VALID_API not in rec.getMessage()
    assert "[REDACTED-TOKEN]" in rec.getMessage()


def test_redaction_filter_scrubs_exc_info_traceback():
    """A token inside an exc_info traceback is scrubbed via record.exc_text."""
    f = TokenRedactionFilter()
    try:
        raise RuntimeError("boom " + VALID_API)
    except RuntimeError:
        rec = logging.LogRecord(
            "conduit", logging.ERROR, __file__, 1, "failed", None, sys.exc_info(),
        )
    f.filter(rec)
    rendered = logging.Formatter("%(message)s").format(rec)
    assert VALID_API not in rendered
    assert "[REDACTED-TOKEN]" in rendered


def test_token_regex_rejects_trailing_newline():
    """\\Z anchor (not $) rejects a token with a trailing newline."""
    assert _TOKEN_RE.match(VALID_API) is not None
    assert _TOKEN_RE.match(VALID_API + "\n") is None


def test_install_token_redaction_covers_loggers(caplog):
    f = install_token_redaction()
    try:
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("httpx").debug("url token %s" % VALID_API)
            logging.getLogger("conduit").warning("header " + VALID_CLI)
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert VALID_API not in joined
        assert VALID_CLI not in joined
        assert joined.count("[REDACTED-TOKEN]") == 2
    finally:
        _remove_filter(f)
