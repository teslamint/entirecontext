# EntireContext plugin for omp (Oh My Pi)

Bridges [omp](https://github.com/can1357/oh-my-pi) session lifecycle events to
EntireContext capture, mirroring what the Claude Code hook protocol does.
Ships as an omp plugin (extension + MCP server).

## Why this exists

EC capture (`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop`,
`SessionEnd`) depends on a host calling `ec hook handle --type <HookType>` with
a JSON payload on stdin. omp does not speak the Claude Code hook protocol; it
exposes its own [extension API](https://github.com/can1357/oh-my-pi) with
events named `session_start`, `before_agent_start`, `tool_result`, `turn_end`,
and `session_shutdown`. `extension/index.ts` is the bridge.

## Event mapping

| omp event | EC hook | Payload keys | Source |
|---|---|---|---|
| `session_start` | `SessionStart` | `session_id`, `cwd`, `source` | `src/entirecontext/hooks/session_lifecycle.py:75-77` |
| `before_agent_start` | `UserPromptSubmit` | `session_id`, `cwd`, `prompt` | `src/entirecontext/hooks/turn_capture.py:140-142` |
| `tool_result` | `PostToolUse` | `session_id`, `cwd`, `tool_name`, `tool_input` | `src/entirecontext/hooks/turn_capture.py:297-300` |
| `turn_end` | `Stop` | `session_id`, `cwd` | `src/entirecontext/hooks/turn_capture.py:214-216` |
| `session_shutdown` | `SessionEnd` | `session_id`, `cwd` | `src/entirecontext/hooks/session_lifecycle.py:238-239` |

Two mapping details that are easy to get wrong:

- **`tool_result`, not `tool_call`.** `tool_call` is omp's pre-execution event
  and carries no result; `tool_result` is the documented post-execution event
  with `toolName`/`input` (`omp://hooks.md`, `omp://extensions.md`).
- EC handlers read `cwd` and `prompt` — not `repo_path` / `prompt_text`. An
  earlier draft of this bridge used the wrong keys and silently produced empty
  `user_message` rows. `cwd` is read from the handler's `ctx.cwd` (the
  documented session cwd), not `process.cwd()`.

### Ordering

EC's turn state machine requires `PostToolUse` to land before the `Stop` that
completes a turn (`on_tool_use` only updates an `in_progress` turn;
`on_stop` flips it to `completed`). omp fires `tool_result` and `turn_end`
independently, with no ordering guarantee between concurrent hook spawns, so
every hook call for a session is chained through one FIFO queue
(`sessionQueues` in `extension/index.ts`) instead of spawned independently.

### Duplicate submissions

`before_agent_start` can re-fire for the same prompt (a source-base retry or a
resumed delivery, per `omp://extensions.md`), with no rollback of the first
firing's side effects. The bridge remembers the last submitted prompt per
session and skips a byte-identical repeat, so a retried submission doesn't
create a second `turns` row for the same prompt.

### Context injection format

Context EC surfaces on stdout is fed back into the session as a `custom`
message. The two hooks that print it use different shapes:

- `SessionStart` prints plain text — queued onto the next turn
  (`deliverAs: "nextTurn"`).
- `UserPromptSubmit` prints a JSON envelope,
  `{"hookSpecificOutput":{"additionalContext": "..."}}`
  (`handler.py:373-381`) — the bridge parses this and attaches only
  `additionalContext` to the current turn's `before_agent_start` return value.

## Install

```bash
integrations/omp/install.sh
```

Runs `omp plugin link` on this directory (symlinks it into
`~/.omp/plugins/node_modules/entirecontext-omp`, so local edits are picked
up). Verify the link with `omp plugin list`.

MCP discovery: `plugin-manager-installer-plumbing.md` states the
`omp-plugins` capability provider scans `.mcp.json` "under enabled npm/link
plugin roots", which is what `omp plugin link` creates. That is the documented
mechanism; runtime discovery was not exercised in this session (there is no
non-interactive `omp mcp list`). Confirm in a live session with `/mcp list`
and expect an `entirecontext` server.

Before linking, the script backs up and removes any pre-existing native
extension at `<agent-dir>/extensions/entirecontext` (an earlier manual-copy
install method some drafts of this bridge used). That file is a **separate
artifact** the runtime does not deduplicate against the linked plugin, so
leaving it in place makes every hook fire twice. The backup moves to
`<agent-dir>/extensions-backup/`, outside the directory omp scans for
extensions — leaving it inside `extensions/` (even renamed) keeps it
discoverable as a second copy, since the loader scans one level deep for a
`subdir/index.ts` or `subdir/package.json`.

Restart omp (or start a new session) after installing — extensions load once
at session start.

## MCP server

`.mcp.json` declares the `ec mcp serve` stdio server. Requires the
`entirecontext[mcp]` extra installed for the active `ec`.

## Verification

Typecheck and a load smoke test:

```bash
cd integrations/omp
npm install
./node_modules/.bin/tsc -p tsconfig.json
bun -e 'const m = await import("./extension/index.ts"); console.log(typeof m.default)'  # -> "function"
```

End-to-end (drives the real extension with a synthetic `pi` host, captures the
JSON payloads it actually sends via a fake `ec` shim on `PATH`, replays them
through the real `ec hook handle` in a throwaway `ec init`-ed repo, then
asserts the resulting turn's `user_message` and `tools_used`):

```bash
./verify.sh   # prints PASS[<scenario>] per scenario, then ALL PASS
```

Gitignore hygiene:

```bash
git ls-files -o --exclude-standard integrations/
# expect exactly: extension/index.ts install.sh verify.sh .mcp.json
#                 package.json package-lock.json README.md tsconfig.json
```

## Limitations

- The extension is loaded once at session start; editing it requires a new
  omp session.
- EC only records activity in a repository already initialized with
  `ec init`; `ctx.cwd` at each event must resolve to that repository (or a
  descendant of it).
- `session_id` is read from `ctx.sessionManager.getSessionId()`, falling back
  to `pi.getSessionName()`. If both are unavailable the session id is empty
  and EC handlers that require it (`UserPromptSubmit`, `PostToolUse`, `Stop`)
  no-op for that event.
- Each `ec hook handle` invocation is bounded to 3 seconds; a slower hook is
  killed and treated as producing no surfaced context, so a turn is never
  blocked indefinitely on EC.
- `session_lifecycle.py:108` hardcodes `session_type="claude"` for every
  session regardless of caller — omp sessions are recorded with
  `session_type='claude'` in the EC database, not `'omp'`. This is EC-side
  behavior outside this plugin's scope; do not rely on `session_type` to tell
  omp sessions apart from Claude Code sessions in queries or dashboards.
- The duplicate-submission guard compares exact prompt text per session and
  is reset on `turn_end`, so it only covers omp's pre-turn retry window. A
  byte-identical prompt sent as a genuine new turn ("continue", "yes") is
  captured normally.
