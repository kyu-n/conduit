# Setting up the conduit MCP server in Hermes and Pi

`conduit` is a stdio MCP server exposed by the `conduit-mcp` console command. It
is a **per-developer** server: each developer runs their own copy and
authenticates with their own Phorge API token. Nothing is shared but the code.

This guide covers **Hermes** and **Pi**. For Claude Code, see the main
[README](../README.md#install-from-this-fork).

## Shared prerequisites

1. **`uv`** (provides `uvx`). If missing:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **A Phorge API token.** Generate one at `Settings -> Conduit API Tokens` on
   the Phorge instance. It must be exactly 32 characters (`api-` + 28). The
   server refuses to start otherwise.
3. **The launch command and env**, used by every client below:
   - Command: `uvx`
   - Args: `--from git+https://github.com/kyu-n/conduit.git@master conduit-mcp`
     (for local dev you can instead point at `<clone>/.venv/bin/conduit-mcp`)
   - Env: `PHABRICATOR_URL=https://<your-phorge-host>/api/` and
     `PHABRICATOR_TOKEN=<your 32-char token>`

---

## Hermes

Hermes has native MCP support. Servers are declared in `~/.hermes/config.yaml`
under `mcp_servers:`.

1. Add the server (this file is per-user and local; put your real token here, but
   do not commit it anywhere):
   ```yaml
   # ~/.hermes/config.yaml
   mcp_servers:
     conduit:
       command: uvx
       args:
         - "--from"
         - "git+https://github.com/kyu-n/conduit.git@master"
         - "conduit-mcp"
       env:
         PHABRICATOR_URL: "https://<your-phorge-host>/api/"
         PHABRICATOR_TOKEN: "api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
       # optional:
       # timeout: 30
       # connect_timeout: 45
   ```
2. Restart Hermes:
   ```bash
   hermes
   ```
   The `pha_*` tools are then available automatically.

---

## Pi (badlogic / earendil-works)

Pi **does not support MCP in its core** by design (the project's stance is that
MCP is too context-heavy; Pi favours CLI-tools-with-READMEs). To use an MCP
server with Pi you install the third-party **pi-mcp-adapter**, which exposes MCP
servers through a single proxy tool.

1. Install the adapter:
   ```bash
   pi install npm:pi-mcp-adapter
   ```
2. Declare the server in Pi's MCP config. The adapter reads, in precedence order,
   `~/.config/mcp/mcp.json`, `~/.pi/agent/mcp.json`, `.mcp.json`, `.pi/mcp.json`.
   Pi's config supports `${VAR}` / `$env:VAR` interpolation, so the token stays
   out of the file:
   ```json
   {
     "mcpServers": {
       "conduit": {
         "command": "uvx",
         "args": [
           "--from",
           "git+https://github.com/kyu-n/conduit.git@master",
           "conduit-mcp"
         ],
         "env": {
           "PHABRICATOR_URL": "https://<your-phorge-host>/api/",
           "PHABRICATOR_TOKEN": "${PHABRICATOR_TOKEN}"
         },
         "lifecycle": "lazy"
       }
     }
   }
   ```
   Export your token so the interpolation resolves:
   ```bash
   export PHABRICATOR_TOKEN=api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. Use the tools through the adapter's `mcp` proxy:
   - discover: `mcp({ search: "task" })`
   - inspect: `mcp({ describe: "pha_task_get" })`
   - call: `mcp({ tool: "pha_task_get", args: '{"task_id": "7299"}' })`

   To expose the `pha_*` tools as first-class Pi tools instead of going through
   the proxy, add `"directTools": true` (or a list of tool names) to the server
   entry.

Note: the `tackle` skill ships as a Claude Code skill and references tools as
`mcp__conduit__*`. Under Pi the same tools are reached via the `mcp` proxy (or as
`directTools`), so port the skill's prose accordingly if you want it in Pi.

---

## Sources

- Pi coding agent: <https://github.com/badlogic/pi-mono> and <https://pi.dev>
- Pi's no-MCP stance: <https://mariozechner.at/posts/2025-11-30-pi-coding-agent/>
- pi-mcp-adapter: <https://github.com/nicobailon/pi-mcp-adapter> /
  <https://nicobailon-pi-mcp-adapter.mintlify.app/introduction>
