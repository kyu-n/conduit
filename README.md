# Conduit - The MCP Server for Phabricator and Phorge
Conduit is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) server that provides seamless integration with Phabricator and Phorge APIs, enabling advanced automation and interaction capabilities for developers and tools.

> **AI agents:** if you are an agent (Claude Code, Codex, Gemini CLI, Hermes, or Pi)
> setting yourself up to use this server, follow
> [`docs/AGENT_SETUP.md`](docs/AGENT_SETUP.md) start to finish. It is an
> agent-addressed runbook with per-agent registration and a self-check.

## Features
**Modern HTTP Client**: Built with `httpx` for HTTP/2 support and better performance

**MCP Integration**: Ready-to-use MCP tools for task management

**Type Safety**: Full type hints and runtime validation for better development experience

**Secure**: Token-based authentication with environment variable configuration

**Enhanced Features**:
- Advanced error handling with detailed error codes and suggestions
- Token optimization for efficient API responses
- Smart pagination and intelligent data limiting
- Runtime validation client for type safety
- Configurable client with caching and retry mechanisms

## What this fork adds
Beyond upstream `cortex-app/conduit`:
- **`pha_file_download`** — fetch a file attachment (e.g. a mockup) and return it as a viewable image, or metadata for non-image/oversized files.
- **`pha_task_relationships`** — read a task's direct parents and subtasks, for walking the task tree.
- **Configurable User-Agent** via `PHABRICATOR_USER_AGENT` (some Phorge operators require an identifying UA).
- **Omittable descriptions** in `pha_task_search_advanced`, to save tokens on large result sets.
- **Search-constraint fixes** — several `*.search` client methods (and `differential.setdiffproperty`) sent un-flattened nested constraints that Phorge rejected with a 500; they now route through `build_search_params`.

## Usage
### Via `uvx`
You need to install `uv` first. If it is not installed, run the following command:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
After installation, restart your shell or terminal to apply the environment variable changes.

Then run it standalone (a quick smoke test; for client integration see [Install from this fork](#install-from-this-fork)):
```bash
uvx --from git+https://github.com/kyu-n/conduit.git@main conduit-mcp
```

### Install from this fork

This fork adds two read tools (`pha_file_download`, `pha_task_relationships`)
for fetching file attachments as viewable images and reading a task's
parent/subtask tree, on the `main` branch. It is a per-developer server: each
developer runs their own copy and authenticates with their own Phorge API
token. Nothing is shared except the code.

1. Each developer generates a token at `Settings -> Conduit API Tokens` on the
   Phorge instance and exports it:
   ```bash
   export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx   # exactly 32 chars
   ```
2. Copy [`.mcp.json.example`](.mcp.json.example) to `.mcp.json` at the root of
   the repo you work in, and set `PHABRICATOR_URL` to your Phorge instance.
   Claude Code auto-discovers it and prompts each developer to approve the
   server. The token is read from the environment via `${PHABRICATOR_TOKEN}`, so
   no secrets are committed.

Using a different agent (Codex, Gemini CLI, Hermes, Pi) or want the full
agent-self-setup runbook? See [docs/AGENT_SETUP.md](docs/AGENT_SETUP.md).

### From Source
To install from source for development or contribution:

```bash
# Clone the repository
git clone https://github.com/kyu-n/conduit.git
cd conduit

# Install in development mode with all dependencies
pip install -e .[dev]
```

This will install the package in editable mode with all development dependencies.

### As a Streamable HTTP server
Conduit speaks the MCP **Streamable HTTP** transport for multi-user scenarios:
many clients connect to one server, each authenticating with its own token. The
deprecated HTTP+SSE transport has been removed in favor of it.

Run it bound to loopback for local use:
```bash
conduit-mcp --transport http --host 127.0.0.1 --port 8000 --path /mcp
```
In HTTP mode the server holds no Phabricator credentials. Each request carries
the caller's token in a header, so access is revocable per user at Phorge:
```
X-PHABRICATOR-TOKEN: api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
`PHABRICATOR_TOKEN` is not read in HTTP mode.

#### Exposing it publicly
A non-loopback bind is refused unless you opt in with `CONDUIT_ALLOW_PUBLIC=1`,
which also requires Host/Origin allowlists, turns on DNS-rebinding protection,
and defaults to read-only. The supported public deployment is the
[`docker-compose.yml`](docker-compose.yml): Caddy terminates TLS and rate-limits
per IP, conduit runs behind it on an internal network with no published port.
```bash
cp .env.example .env   # fill in domain, ACME email, Phorge URL, allowlists
docker compose up -d --build
```

The `X-Phabricator-Token` check is a *shape* filter, not authentication: any
well-formed token string passes the gate and can list the tool catalogue and
trigger one Phorge call per request (Phorge, holding the real credentials,
rejects an unissued token, so nothing is exfiltrated). If catalogue disclosure
or that request amplification matters for your exposure, put real authentication
(mTLS or a gateway credential) in front of `/mcp`.

| HTTP-mode variable | Purpose |
|--------------------|---------|
| `CONDUIT_TRANSPORT` | `stdio` (default) or `http`; same as `--transport`. |
| `CONDUIT_ALLOW_PUBLIC` | `1` permits a non-loopback bind. Required for public exposure. |
| `CONDUIT_ALLOWED_HOSTS` | Comma-separated Host values to accept (required when public). |
| `CONDUIT_ALLOWED_ORIGINS` | Comma-separated Origin values to accept (required when public). |
| `CONDUIT_READONLY` | `1`/`0`; drops write tools from the catalogue. Defaults on when public. |

## Configuration
Before running the server, you need to set up the following environment variables:

### Environment Variables
```bash
export PHABRICATOR_TOKEN=your-api-token-here
export PHABRICATOR_URL="https://your-phabricator-instance.com/api/"

export PHABRICATOR_PROXY="socks5://127.0.0.1:1080"  # Optional, if your network is behind a firewall
export PHABRICATOR_DISABLE_CERT_VERIFY=1  # Optional, if your network is under HTTPS filter (WARNING: Disabling certificate verification can expose you to security risks. Only set this if you trust your network environment.)
export PHABRICATOR_USER_AGENT="MyOrg-Phabricator-MCP/1.0 (contact@example.org)"  # Optional, override the default User-Agent header. Some Phabricator/Phorge operators require identifying contact info for rate-limiting purposes.
```
Do note that in HTTP mode, `PHABRICATOR_TOKEN` is NOT needed.

### Getting Your API Token
1. Log into your Phabricator instance
2. Go to Settings > Conduit API Tokens
3. Generate a new token
4. Copy the 32-character token and use it as `PHABRICATOR_TOKEN`

## Contributing
This is a fork maintained at [github.com/kyu-n/conduit](https://github.com/kyu-n/conduit);
file issues and pull requests there. After `pip install -e .[dev]`, run the tests
with `pytest`.

## License
Copyright (c) 2025 mcpnow.io

Licensed under the [MIT](LICENSE) license.
