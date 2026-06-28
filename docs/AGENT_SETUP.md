# Set yourself up to use conduit (AI agent runbook)

**You are reading this because you are an AI coding agent and you (or your
operator) want you to use the conduit MCP server** to read Phorge tasks and
mockups. Follow the steps below in order and run the checks yourself.

- This guide is for **using** the server. To work on conduit's own code, read
  [`AGENTS.md`](../AGENTS.md) instead.
- conduit runs today as a **per-developer stdio server**: you run your own copy
  and authenticate with your own Phorge API token. Nothing is shared but the
  code, so one person's token is never another's.

If at any step a command errors, jump to [Troubleshoot](#5-troubleshoot-run-the-check-that-matches-your-symptom) before continuing.

---

## 0. Which agent are you?

Note who you are now, then work straight down the runbook: do step 1, then **only
your** step 2 subsection, then steps 3 to 5.

| If you are… | tell-tale | go to |
|-------------|-----------|-------|
| **Claude Code** | you call tools like `mcp__server__tool`; a `claude` CLI exists | [2a](#2a-claude-code) |
| **Hermes** | `~/.hermes/config.yaml` exists; you launched via `hermes` | [2b](#2b-hermes) |
| **Pi** | a `pi` CLI exists; MCP is reached through an adapter, not natively | [2c](#2c-pi) |
| **Codex CLI** | a `codex` CLI exists; MCP lives in `~/.codex/config.toml` | [2d](#2d-codex-cli) |
| **Gemini CLI** | a `gemini` CLI exists; MCP lives in `~/.gemini/settings.json` | [2e](#2e-gemini-cli) |

If you are some other agent: any MCP client that launches a stdio server with a
command + env works. Use the launch command in step 1.3 with your client's MCP
config format.

---

## 1. Prerequisites (every agent)

**1.1 — `uv` (provides `uvx`).** Check, and install if missing:
```bash
command -v uvx || curl -LsSf https://astral.sh/uv/install.sh | sh
```
Restart your shell afterward so `uvx` is on `PATH`.

**1.2 — Your Phorge connection details.** You need two values:
- `PHABRICATOR_URL` — the full API URL of the Phorge instance, ending in
  `/api/` and a trailing slash, e.g. `https://<your-phorge-host>/api/`.
- `PHABRICATOR_TOKEN` — your personal API token, exactly **32 characters**
  (`api-` followed by 28 alphanumerics). The server refuses to start if it is not
  32 characters long.

Check whether they are already in your environment:
```bash
echo "${PHABRICATOR_URL:-<unset>}"
echo "${PHABRICATOR_TOKEN:+set}${PHABRICATOR_TOKEN:-<unset>}"
```
If `PHABRICATOR_TOKEN` is unset: **you cannot mint it yourself.** A human
generates it once at `Settings -> Conduit API Tokens` on the Phorge instance.
Stop and ask your operator for a token (and the URL) before continuing.

**1.3 — The launch command** every client below uses (memorize it):
- command: `uvx`
- args: `--from git+https://github.com/kyu-n/conduit.git@main conduit-mcp`
- env: `PHABRICATOR_URL` and `PHABRICATOR_TOKEN` from step 1.2

(For local development against a clone, swap `uvx --from … conduit-mcp` for
`<clone>/.venv/bin/conduit-mcp`.)

---

## 2. Register the server

### 2a. Claude Code

Pick **one** of the two ways.

**Project file (recommended, no secrets committed):** copy the template and set
your URL. The token is read from your environment, so it never lands in the file.
```bash
cp .mcp.json.example .mcp.json   # at the root of the repo you work in
# then edit .mcp.json: set PHABRICATOR_URL to your Phorge instance
export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
Claude Code auto-discovers `.mcp.json` and prompts you to approve the server.

**CLI:** register it directly (here the token is passed explicitly):
```bash
claude mcp add conduit \
  -e PHABRICATOR_URL=https://<your-phorge-host>/api/ \
  -e PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx \
  -- uvx --from git+https://github.com/kyu-n/conduit.git@main conduit-mcp
```

> **Critical:** pass the env with `-e` flags (or the `.mcp.json` `env` block).
> Variables exported in your shell do **not** reach the spawned MCP subprocess;
> a server that can't see `PHABRICATOR_TOKEN` exits on startup and Claude Code
> reports "Failed to connect". **Restart the session** after registering so the
> tools load.

Tools then appear as `mcp__conduit__pha_*`.

### 2b. Hermes

Hermes (the **Nous Research Hermes Agent**) has native MCP support; declare the
server in `~/.hermes/config.yaml` (per-user, local — put your real token here, do
not commit it):
```yaml
# ~/.hermes/config.yaml
mcp_servers:
  conduit:
    command: uvx
    args:
      - "--from"
      - "git+https://github.com/kyu-n/conduit.git@main"
      - "conduit-mcp"
    env:
      PHABRICATOR_URL: "https://<your-phorge-host>/api/"
      PHABRICATOR_TOKEN: "api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    # optional: timeout: 30 / connect_timeout: 45
```
Restart Hermes (`hermes`), or run `/reload-mcp` in-session. The `pha_*` tools are
then available directly.

### 2c. Pi

Pi does not support MCP in its core (the project favors CLI-tools-with-READMEs
over context-heavy MCP). Use the third-party **pi-mcp-adapter**, which proxies
MCP servers through one tool.
```bash
pi install npm:pi-mcp-adapter
```
Declare the server in Pi's MCP config (the adapter reads, in precedence order,
`~/.config/mcp/mcp.json`, `~/.pi/agent/mcp.json`, `.mcp.json`, `.pi/mcp.json`).
Pi interpolates `${VAR}`, so keep the token out of the file:
```json
{
  "mcpServers": {
    "conduit": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kyu-n/conduit.git@main", "conduit-mcp"],
      "env": {
        "PHABRICATOR_URL": "https://<your-phorge-host>/api/",
        "PHABRICATOR_TOKEN": "${PHABRICATOR_TOKEN}"
      },
      "lifecycle": "lazy"
    }
  }
}
```
```bash
export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
Reach the tools through the adapter's `mcp` proxy (a tool's `args`, when it takes
any, is passed as a JSON string), or add `"directTools": true` to the server entry
to expose them as first-class Pi tools.

### 2d. Codex CLI

Codex reads MCP servers from `~/.codex/config.toml` (or a project-scoped
`.codex/config.toml` in a trusted project). Add a `[mcp_servers.conduit]` table; to
keep the token out of the file, forward it from your shell with `env_vars` and put
only the URL in `env`:
```toml
[mcp_servers.conduit]
command = "uvx"
args = ["--from", "git+https://github.com/kyu-n/conduit.git@main", "conduit-mcp"]
env_vars = ["PHABRICATOR_TOKEN"]            # forwarded from your environment
[mcp_servers.conduit.env]
PHABRICATOR_URL = "https://<your-phorge-host>/api/"
```
```bash
export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
Or register in one line (token passed inline; `--` separates Codex's flags from the
server command):
```bash
codex mcp add conduit \
  --env PHABRICATOR_URL=https://<your-phorge-host>/api/ \
  --env PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx \
  -- uvx --from git+https://github.com/kyu-n/conduit.git@main conduit-mcp
```
Confirm with `/mcp` in the Codex TUI; the `pha_*` tools then load.

### 2e. Gemini CLI

Gemini reads MCP servers from `~/.gemini/settings.json` (user) or
`.gemini/settings.json` (project), under `mcpServers`. Gemini expands `$VAR` in the
`env` block, so the token stays out of the file:
```json
{
  "mcpServers": {
    "conduit": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kyu-n/conduit.git@main", "conduit-mcp"],
      "env": {
        "PHABRICATOR_URL": "https://<your-phorge-host>/api/",
        "PHABRICATOR_TOKEN": "$PHABRICATOR_TOKEN"
      }
    }
  }
}
```
```bash
export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
Or register from the CLI (stdio is the default transport; `-e` sets env, and the
server command follows the name):
```bash
gemini mcp add \
  -e PHABRICATOR_URL=https://<your-phorge-host>/api/ \
  -e PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx \
  conduit uvx --from git+https://github.com/kyu-n/conduit.git@main conduit-mcp
```
Verify with `/mcp` in chat (or `gemini mcp list`). Gemini exposes every tool under a
fully-qualified name `mcp_<server>_<tool>`, so conduit's identity tool is
`mcp_conduit_pha_user_whoami`.

---

## 3. Verify the config (run this yourself)

Before going through your client, confirm the server itself starts with your
env. Run it standalone:
```bash
PHABRICATOR_URL=https://<your-phorge-host>/api/ \
PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx \
uvx --from git+https://github.com/kyu-n/conduit.git@main conduit-mcp
```
- **Good:** it prints nothing on stdout and **hangs**, waiting for stdio JSON-RPC. Your
  config is valid (FastMCP may print a startup banner to stderr; that's fine).
  Press Ctrl-C to exit.
- **Bad:** it exits immediately with `PHABRICATOR_TOKEN is required`,
  `... must be exactly 32 characters`, or `PHABRICATOR_URL ... is required`.
  Fix the env (step 1.2) and rerun.

## 4. Verify end-to-end (call a tool)

Through your client, call the identity tool. It should return your Phorge
username, which proves the token authenticates:

| Agent | how to call it |
|-------|----------------|
| Claude Code | call tool `mcp__conduit__pha_user_whoami` |
| Hermes | call tool `pha_user_whoami` |
| Pi | `mcp({ tool: "pha_user_whoami" })`, or `pha_user_whoami` if you set `directTools` |
| Codex CLI | call tool `pha_user_whoami` (listed via `/mcp` in the Codex TUI) |
| Gemini CLI | call tool `mcp_conduit_pha_user_whoami` (the FQN; `/mcp` lists them) |

If it returns your user, you are set up. Tool names follow `pha_<area>_<action>`
(e.g. `pha_task_get`, `pha_task_relationships`, `pha_file_download`); discover
the full set via your client's tool list.

---

## 5. Troubleshoot (run the check that matches your symptom)

- **Startup error `PHABRICATOR_TOKEN is required` / `Failed to connect`** — the
  env is not reaching the subprocess. Claude Code: use `-e` flags or the
  `.mcp.json` `env` block, not your shell export. Hermes/Pi: put the values in
  the `env:` block. Then **restart the session/agent**.
- **`... must be exactly 32 characters`** — the token is not `api-` + 28 (36 or
  the raw 28 are common mistakes). Copy the whole `api-…` string.
- **404 / connection refused / wrong content** — `PHABRICATOR_URL` must be the
  full `https://<host>/api/` (include `/api/` and the trailing slash), not the
  web UI root.
- **Behind a corporate proxy** — add `PHABRICATOR_PROXY=socks5://127.0.0.1:1080`
  (or your proxy) to the same `env`.
- **Self-signed / intercepted TLS** — add `PHABRICATOR_DISABLE_CERT_VERIFY=1`
  (only on a network you trust; it disables certificate verification).
- **Some Phorge operators require an identifying User-Agent** — add
  `PHABRICATOR_USER_AGENT="MyOrg-conduit/1.0 (contact@example.org)"`.

---

## Sources (for the per-agent specifics)

- Codex MCP: <https://developers.openai.com/codex/mcp> (config reference:
  <https://developers.openai.com/codex/config-reference>)
- Gemini CLI MCP:
  <https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md>
- Hermes Agent (Nous Research) MCP guide:
  <https://hermes-agent.nousresearch.com/docs/guides/use-mcp-with-hermes>
- Pi coding agent: <https://github.com/earendil-works/pi> / <https://pi.dev>
- Pi's no-MCP stance: <https://mariozechner.at/posts/2025-11-30-pi-coding-agent/>
- pi-mcp-adapter: <https://github.com/nicobailon/pi-mcp-adapter>
