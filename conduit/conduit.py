import argparse
import ipaddress
import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.middleware import Middleware

from conduit.client import PhabricatorClient
from conduit.client.base import DEFAULT_USER_AGENT
from conduit.http_security import TokenGate, register_health, _TOKEN_RE
from conduit.main_tools import register_tools

logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING),
)
logger = logging.getLogger("conduit")


class PhabricatorConfig(object):
    def __init__(self, token=None, require_token=True, http_mode=False):
        if http_mode:
            # HTTP mode supplies the token per-request via header; never read env.
            self.token = None
        else:
            self.token = token or os.getenv("PHABRICATOR_TOKEN")

        self.url = os.getenv("PHABRICATOR_URL")
        self.proxy = os.getenv("PHABRICATOR_PROXY")
        self.disable_cert_verify = os.getenv(
            "PHABRICATOR_DISABLE_CERT_VERIFY", ""
        ).lower() in ("1", "true", "yes")
        self.user_agent = os.getenv("PHABRICATOR_USER_AGENT") or None

        if not http_mode and require_token and not self.token:
            raise ValueError("PHABRICATOR_TOKEN is required")

        if not self.url:
            raise ValueError("PHABRICATOR_URL environment variable is required")

        if self.token and len(self.token) != 32:
            raise ValueError("PHABRICATOR_TOKEN must be exactly 32 characters long")

        if not self.url.startswith(("http://", "https://")):
            raise ValueError("PHABRICATOR_URL must start with http:// or https://")

        if self.url and not self.url.endswith("/"):
            self.url += "/"

    @property
    def api_headers(self):
        return {"Content-Type": "application/x-www-form-urlencoded"}

    @property
    def base_params(self):
        return {"api.token": self.token}


class ConduitApp:
    """Main application class for Conduit MCP Server."""

    def __init__(self, config: PhabricatorConfig, http_mode: bool = False):
        self.config = config
        self.http_mode = http_mode
        self._shared_client = None
        self._client = None
        if http_mode:
            self.mcp = FastMCP("Conduit", lifespan=self._lifespan)
        else:
            self.mcp = FastMCP("Conduit")

    @asynccontextmanager
    async def _lifespan(self, server):
        # server is the FastMCP instance; ignored here.
        self._shared_client = httpx.Client(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.config.user_agent or DEFAULT_USER_AGENT,
            },
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            proxy=self.config.proxy,
            verify=not self.config.disable_cert_verify,
        )
        try:
            yield
        finally:
            self._shared_client.close()

    def get_client(self):
        """Return a Phabricator client for the current request."""
        if self.http_mode:
            if self._shared_client is None:
                raise RuntimeError(
                    "Shared HTTP client is not initialized; "
                    "the server lifespan has not started."
                )
            headers = get_http_headers()
            http_token = headers.get("x-phabricator-token")

            if not http_token:
                raise ValueError(
                    "Must provide X-Phabricator-Token header in HTTP mode."
                )

            if not _TOKEN_RE.match(http_token):
                raise ValueError(
                    "X-Phabricator-Token must match api-<28 alnum chars> or "
                    "cli-<28 alnum chars>."
                )

            return PhabricatorClient(
                self.config.url,
                http_token,
                http_client=self._shared_client,
            )

        # stdio mode: cache a single client
        if self._client is not None:
            return self._client

        if not self.config.token:
            raise ValueError("PHABRICATOR_TOKEN is required for stdio mode")

        self._client = PhabricatorClient(
            self.config.url,
            self.config.token,
            proxy=self.config.proxy,
            disable_cert_verify=self.config.disable_cert_verify,
            user_agent=self.config.user_agent,
        )
        return self._client

    def register_tools(self):
        """Register all MCP tools."""
        register_tools(self.mcp, self.get_client)

    def run_http_mode(self, host: str, port: int, path: str):
        """Run in Streamable HTTP mode (loopback-only in M1)."""
        if host == "localhost":
            is_loopback = True
        else:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False

        if not is_loopback:
            raise ValueError(
                f"Non-loopback bind refused (M1): '{host}'. "
                "Use --host 127.0.0.1 (or localhost) with --transport http."
            )

        logger.info("Starting in HTTP mode on %s:%s%s", host, port, path)
        register_health(self.mcp)
        self.mcp.run(
            transport="http",
            host=host,
            port=port,
            path=path,
            stateless_http=True,
            json_response=True,
            middleware=[Middleware(TokenGate)],
        )

    def run_stdio_mode(self):
        """Run the application in stdio mode."""
        logger.info("Starting in stdio mode")
        self.mcp.run(transport="stdio")


# Global app instance (backward compat)
_app = None


def print_server_info(config):
    """Print server configuration information."""
    logger.info("Starting Conduit MCP Server...")
    logger.info("Phabricator URL: %s", config.url)
    logger.info("Token configured: %s", "Yes" if config.token else "No")
    logger.info("Proxy configured: %s", "Yes" if config.proxy else "No")
    if config.proxy:
        logger.info("Proxy URL: %s", config.proxy)
    logger.info(
        "SSL certificate verification: %s",
        "Disabled" if config.disable_cert_verify else "Enabled",
    )


def main():
    """Main entry point for the Conduit MCP Server."""
    parser = argparse.ArgumentParser(
        description="Conduit MCP Server for Phabricator and Phorge"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("CONDUIT_TRANSPORT"),
        help="Transport to use: stdio (default) or http",
    )
    parser.add_argument(
        "--host",
        "-H",
        default="127.0.0.1",
        help="Host to bind to for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to bind to for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="Path for the HTTP transport endpoint (default: /mcp)",
    )

    args = parser.parse_args()

    # Bare --host/--port without --transport is a hard error pointing at --transport http.
    if args.transport is None:
        has_host_port = any(a in sys.argv for a in ["--host", "-H", "--port", "-p"])
        if has_host_port:
            print(
                "Error: --host/--port without --transport is not supported. "
                "Add --transport http explicitly.",
                file=sys.stderr,
            )
            sys.exit(1)
        args.transport = "stdio"

    if args.transport == "http":
        config = PhabricatorConfig(http_mode=True)
        print_server_info(config)
        app = ConduitApp(config, http_mode=True)
        app.register_tools()
        app.run_http_mode(args.host, args.port, args.path)
    else:
        config = PhabricatorConfig(require_token=True)
        print_server_info(config)
        app = ConduitApp(config, http_mode=False)
        app.register_tools()
        app.run_stdio_mode()


# Backward compatibility functions
def get_config():
    """Get configuration for backward compatibility."""
    return PhabricatorConfig(require_token=False)


def get_client():
    """Get client for backward compatibility."""
    config = get_config()
    return PhabricatorClient(
        config.url,
        config.token or "dummy_token",
        proxy=config.proxy,
        disable_cert_verify=config.disable_cert_verify,
    )


if __name__ == "__main__":
    main()
