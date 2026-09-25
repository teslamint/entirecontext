# EntireContext plugin for omp (Oh My Pi)

The plugin connects [omp](https://github.com/can1357/oh-my-pi) session lifecycle events to EntireContext (EC) capture,
as the Claude Code hook protocol does. It ships as an omp plugin with an
extension and a Model Context Protocol (MCP) server.

## Why this exists

EC capture for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop`, and
`SessionEnd` depends on a host. That host calls
`ec hook handle --type <HookType>` with a JavaScript Object Notation (JSON)
payload on standard input (stdin).
omp does not use the Claude Code hook protocol. It exposes its own
[extension application programming interface (API)](https://github.com/can1357/oh-my-pi) with events named `session_start`,
`before_agent_start`, `tool_result`, `turn_end`, and `session_shutdown`.
`extension/index.ts` connects those events to EC.

## Event mapping

| omp event | EC hook | Payload keys | Source |
|---|---|---|---|
| `session_start` | `SessionStart` | `session_id`, `cwd`, `source` | `src/entirecontext/hooks/session_lifecycle.py:75-77` |
| `before_agent_start` | `UserPromptSubmit` | `session_id`, `cwd`, `prompt` | `src/entirecontext/hooks/turn_capture.py:140-142` |
| `tool_result` | `PostToolUse` | `session_id`, `cwd`, `tool_name`, `tool_input` | `src/entirecontext/hooks/turn_capture.py:297-300` |
| `turn_end` | `Stop` | `session_id`, `cwd` | `src/entirecontext/hooks/turn_capture.py:214-216` |
| `session_shutdown` | `SessionEnd` | `session_id`, `cwd` | `src/entirecontext/hooks/session_lifecycle.py:238-239` |

Check these two mapping details:

- **`tool_result`, not `tool_call`.** `tool_call` is omp's pre-execution event
  and carries no result; `tool_result` is the documented post-execution event
  with `toolName`/`input` (`omp://hooks.md`, `omp://extensions.md`).
- EC handlers read `cwd` and `prompt` — not `repo_path` / `prompt_text`. An
  earlier draft of this bridge used the wrong keys and silently produced empty
  `user_message` rows. The handler reads `cwd` from `ctx.cwd`, the documented
  session cwd, not `process.cwd()`.

### Ordering

EC's turn state machine requires `PostToolUse` before `Stop` completes a turn.
`on_tool_use` only updates an `in_progress` turn. `on_stop` changes the turn
state to `completed`.
omp fires `tool_result` and `turn_end` independently, with no ordering
guarantee between concurrent hook spawns. The bridge chains every hook call
for a session through one first-in, first-out (FIFO) queue (`sessionQueues` in
`extension/index.ts`) instead of spawning them independently.

### Duplicate submissions

`before_agent_start` can fire again for the same prompt. The cause can be a
source-base retry or a resumed delivery, per `omp://extensions.md`. The first
firing's side effects do not roll back.
The bridge remembers the last submitted prompt for each session. It skips a
byte-identical repeat. A retried submission therefore does not create a second
`turns` row for the same prompt.

### Context injection format

The bridge sends context that EC prints to standard output (stdout) back into
the session as a `custom` message. The two hooks that print it use different
shapes:

- The bridge queues plain text from `SessionStart` onto the next turn
  (`deliverAs: "nextTurn"`).
- `UserPromptSubmit` prints a JSON envelope,
  `{"hookSpecificOutput":{"additionalContext": "..."}}` (`handler.py:373-381`).
  The bridge parses the envelope. It attaches only `additionalContext` to the
  current turn's `before_agent_start` return value.

## Install

```bash
integrations/omp/install.sh
```

The script runs `omp plugin link` on this directory. It creates a symlink in
`~/.omp/plugins/node_modules/entirecontext-omp`, so local edits take effect.
Verify the link with `omp plugin list`.

`plugin-manager-installer-plumbing.md` says that the `omp-plugins` capability
provider scans `.mcp.json` "under enabled npm/link plugin roots". The
`omp plugin link` command creates a root of this type.
We did not test runtime discovery in this session because no non-interactive
`omp mcp list` exists. Confirm discovery in a live session with `/mcp list`.
Expect an `entirecontext` server.

Before linking, the script backs up any existing native extension at
`<agent-dir>/extensions/entirecontext`. The script then removes it. Earlier
bridge drafts used this manual-copy install method.
That file is a separate artifact. The runtime does not deduplicate it against
the linked plugin. Leaving it in place makes every hook fire twice.

The script moves the backup to `<agent-dir>/extensions-backup/`, outside the
directory omp scans for extensions. If the backup stays inside `extensions/`,
even with a new name, the loader discovers it as a second copy. The loader
scans one level deep for a `subdir/index.ts` or `subdir/package.json`.

Restart omp or start a new session after installing. Extensions load once at
session start.

## MCP server

The `.mcp.json` file declares the `ec mcp serve` server. It uses standard
input/output (stdio). The active `ec` installation must include the
`entirecontext[mcp]` extra.

## Verification

Run a typecheck. Run a load smoke test:

```bash
cd integrations/omp
npm install
./node_modules/.bin/tsc -p tsconfig.json
bun -e 'const m = await import("./extension/index.ts"); console.log(typeof m.default)'  # -> "function"
```

The end-to-end check drives the real extension with a synthetic `pi` host.
It captures the JSON payloads that the extension sends through a fake `ec`
shim on `PATH`. It replays them through the real `ec hook handle` in a
throwaway `ec init`-ed repo. The check verifies the resulting turn's
`user_message` and `tools_used`.

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

- omp loads the extension once at session start. Start a new omp session after
  you edit the extension.
- EC records activity only in a repository that `ec init` has initialized. At
  each event, `ctx.cwd` must resolve to that repository or one of its
  descendants.
- The plugin reads `session_id` from `ctx.sessionManager.getSessionId()`. If
  that call cannot provide a value, the plugin uses `pi.getSessionName()`. If
  both calls return no value, the session id is empty. EC handlers that
  require the id (`UserPromptSubmit`, `PostToolUse`, `Stop`) do no work for
  that event.
- The bridge stops each `ec hook handle` invocation after 3 seconds. If a hook
  takes longer, the bridge kills it. The bridge treats the hook as producing no
  surfaced context. A turn therefore never waits indefinitely for EC.
- `session_lifecycle.py:108` sets `session_type="claude"` for every session,
  regardless of caller. The EC database records omp sessions as
  `session_type='claude'`, not `session_type='omp'`. This behavior belongs to
  EC, not this plugin. Do not use `session_type` to distinguish omp sessions
  from Claude Code sessions in queries or dashboards.
- The duplicate-submission guard compares exact prompt text within each
  session. It resets at `turn_end`. Therefore, it only covers omp's pre-turn
  retry window. The bridge captures a byte-identical prompt normally when it
  arrives as a genuine new turn ("continue", "yes").
