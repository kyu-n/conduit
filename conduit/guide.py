"""Agent-facing usage guide for conduit, served at runtime.

Single source of truth for "how do I use this server": the `conduit_guide` tool
returns GUIDE, and the `tackle` prompt returns tackle_prompt(task_id). Both are
registered by register_guide(mcp). Keeping the text here (in the package) means the
tool and prompt work however the server was installed, with nothing to keep in sync.
"""

from mcp.types import ToolAnnotations

GUIDE = """\
# Using conduit (a Phorge / Phabricator MCP server)

conduit exposes Phorge's Conduit API as MCP tools named `pha_<area>_<action>`
(plus this `conduit_guide` tool and a `tackle` prompt). If you are unsure how to
do something, the catalogue and workflows below are the map.

## Tool names differ by client
The base names below are `pha_*`. Your MCP client may namespace them: Claude Code
exposes `mcp__conduit__pha_*`, Gemini CLI `mcp_conduit_pha_*`, Pi reaches them via
its `mcp` proxy, Hermes/Codex call them by base name. Use whatever form your client
lists; the arguments are identical. (See AGENT_SETUP.md for the per-client form.)

## Tool catalogue
Tasks (Maniphest):
- `pha_task_get` — one task by id (`T123` or `123`; flat maniphest.info shape).
- `pha_task_get_transactions` — a task's comment/change history.
- `pha_task_relationships` — a task's direct parents and subtasks (tree walking).
- `pha_task_search_advanced` — search tasks (constraints, presets; see Pagination).
- `pha_task_get_personal` — tasks assigned to (or authored by) the authenticated user.
- `pha_task_create`, `pha_task_add_comment`, `pha_task_update`,
  `pha_task_update_relationships` — WRITES (mutate the instance).
Files:
- `pha_file_download` — fetch a file (e.g. a mockup); returns a viewable image for
  images under the size cap, else metadata with a `uri`.
Users:
- `pha_user_whoami` — the authenticated user (use this to confirm your token works).
- `pha_user_search` — find users.
Projects / workboards:
- `pha_project_search`, `pha_project_get` — read; `pha_project_create`,
  `pha_project_update` — WRITES.
- `pha_workboard_search_columns`, `pha_workboard_search_tasks_by_column` — read a
  board; `pha_workboard_move_task` — WRITE (moves a card).
Repositories (Diffusion):
- `pha_repository_search`, `pha_repository_info`, `pha_repository_browse`,
  `pha_repository_file_content`, `pha_repository_history`,
  `pha_repository_commits_search`, `pha_repository_branches` — read;
  `pha_repository_create` — WRITE.
Code review (Differential):
- `pha_diff_search`, `pha_diff_get`, `pha_diff_get_content`,
  `pha_diff_get_commit_message` — read; `pha_diff_create`,
  `pha_diff_create_from_content`, `pha_diff_update`, `pha_diff_add_comment` — WRITES.

## Read vs write
The read tools above are safe to call freely. The ones marked WRITE change the
Phorge instance (new tasks, comments, status changes, moved cards). Call them only
when the user asked for a change. A read-only deployment does not register the
WRITE tools at all, so they are absent from `tools/list`: trust the live tool list
over this catalogue, and if a WRITE tool is missing the server is read-only.

## Task ids
- `pha_task_get`, `pha_task_relationships`, and `pha_file_download` accept either form:
  the `T`/`F` prefix is optional (`T7229` or `7229`; `F123`/`123`/a `PHID-...`).
- `pha_task_get_transactions` wants a numeric id (a non-numeric value is treated as a
  PHID): pass `7229`.

## Mockups embedded in tasks
Descriptions and comments come back as raw Remarkup. Image attachments appear as
embeds like `{F123}` or `{F123, size=full}`. To pull them:
1. Scan the description AND each comment body with the regex `\\{F(\\d+)[^}]*\\}`
   (the trailing `[^}]*` matters: designers write `{F123, size=full}`, not `{F123}`).
2. Dedup the ids.
3. Call `pha_file_download` with `F<id>` for each. You get a viewable image, or a
   metadata dict (with a `uri`) for non-images / oversized files. Note: some Phorge
   installs omit mimeType from file.search, so image detection falls back to the
   filename extension; a mockup saved without an extension may return as non-image,
   in which case open it via the `uri`.

## Search and pagination
Search tools return at most ~100 results per call and are NOT exhaustive by default.
For "all" / "every" / "identify all X" questions, pass `fetch_all=True` to get the
complete set in one call (it loops the cursor server-side up to a safety cap and
reports `hit_cap` if it stopped early). Otherwise the response carries `has_more`
and `next_cursor`; a partial result says so in a `note`. Never present a single
page as the complete set for an aggregate question.

## The "tackle a task" workflow
Turn "tackle T7229" / "review the tree under T7100" into:
1. Read intent. Pick a traversal depth from the phrasing:
   - Single ("tackle T7229", "pick up ..."): the task plus one
     `pha_task_relationships` call for parent/sibling context.
   - Tree ("the tree under ...", "review this cluster"): recurse
     `pha_task_relationships` from the root, bounded (~depth 3, ~25 nodes). If the
     bound truncates the walk, say so; never silently cap.
   - One-hop: if the body/comments mention other tasks as `T123`, pull those once
     for context (do not recurse from them).
2. Fetch the task with `pha_task_get` (id `T123` or `123`): title, description (raw
   Remarkup with `{F..}` embeds), status/statusName, priority, objectName, uri,
   dependsOnTaskPHIDs. Then `pha_task_get_transactions` for comments
   (`comments[].content.raw`).
3. Mockups: collect `{F..}` ids (description + comments), dedup, `pha_file_download`
   each, view them, and tie each image to where it appeared. Cap at ~10; if more,
   say how many you skipped.
4. Navigate per the chosen depth, summarizing each node (what it is, its status).
5. Act on it: summarize the task and what the mockups show, then proceed with the
   user's actual task (the code change, the review, the answer). Mockups are usually
   rough; align to intent, not pixels.

The `tackle` prompt packages steps 1-5 for a given task id; request it from your
client's prompt list if it supports MCP prompts.

## Failure modes
- Server refuses to start: missing `PHABRICATOR_URL`/`PHABRICATOR_TOKEN`, or a
  non-32-char token. Fix the env (see AGENT_SETUP.md).
- Invalid / revoked token: the call returns an AUTH_ERROR; check your token.
- Not found / permission denied: surface the Conduit error, do not guess.
"""


def tackle_prompt(task_id: str) -> str:
    """The tackle workflow, specialized to one task id (served by the `tackle` prompt)."""
    return f"""\
Tackle Phorge task {task_id} using the conduit tools.

1. Read intent from how the request was phrased and pick a traversal depth:
   single (the task + one parent/sibling lookup), tree (recurse parents/subtasks,
   bounded ~depth 3 / ~25 nodes, and say so if the bound truncates), or one-hop
   (also pull any T-id tasks mentioned in the body/comments, without recursing).
2. Fetch the task: call pha_task_get with the id ({task_id}, with or without a
   leading 'T'). Read title, description (raw Remarkup), status, priority, uri.
   Then pha_task_get_transactions for the comment history (pass the numeric id).
3. Mockups: scan the description and each comment for embeds matching
   \\{{F(\\d+)[^}}]*\\}}, dedup the ids, and call pha_file_download with F<id> for
   each. View the images and tie each to where it appeared. Cap at ~10; report any
   skipped.
4. Navigate with pha_task_relationships per the chosen depth, summarizing each node.
5. Summarize the task and what the mockups show, then proceed with the actual work.

This is a read/navigate workflow. Only use the write tools (create/comment/update/
move) if the user explicitly asks to change the tracker. Call the conduit_guide
tool if you need the full tool catalogue or gotchas.
"""


def register_guide(mcp):
    """Register the conduit_guide tool and the tackle prompt on an MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def conduit_guide() -> str:
        """How to use this server: tool catalogue, the tackle workflow, id handling,
        mockup embeds, pagination, and gotchas. Call this first if you are unsure how
        to navigate Phorge with conduit."""
        return GUIDE

    @mcp.prompt
    def tackle(task_id: str) -> str:
        """Read a Phorge/Maniphest task, view its mockups, navigate related tasks to
        the depth the request implies, then act on it."""
        return tackle_prompt(task_id)
