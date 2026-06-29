# Using conduit

Connecting an agent to conduit is covered in [`AGENT_SETUP.md`](AGENT_SETUP.md).
This is the other half: once connected, how an agent actually *drives* conduit to
navigate a Phorge instance (which tool, in what order, the gotchas).

That workflow knowledge is delivered to agents **at runtime**, so it works for any
MCP client without per-agent wiring:

- **`conduit_guide` tool** — every MCP client surfaces tools to the model, so any
  agent (Claude Code, Codex, Gemini, Hermes, Pi, …) can call `conduit_guide` to get
  the full guide: the tool catalogue, the "tackle a task" workflow (read a task,
  view its mockups, walk the task tree), id handling, mockup embeds, search
  pagination, and failure modes. An agent unsure how to proceed should call this first.
- **`tackle` prompt** — clients that support MCP prompts can request the `tackle`
  prompt with a task id to get a ready-to-run, step-by-step workflow for that task.

Both are served from a single source, [`conduit/guide.py`](../conduit/guide.py)
(`GUIDE` and `tackle_prompt`), so the tool and the prompt never drift. To read the
guide without a client:

```bash
python -c "from conduit.guide import GUIDE; print(GUIDE)"
```
