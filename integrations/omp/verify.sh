#!/usr/bin/env bash
# End-to-end contract check for the EntireContext omp plugin.
#
# Each scenario drives the real extension with a synthetic `pi` host,
# capturing the exact JSON payloads it sends to `ec` via a fake `ec` shim on
# PATH, then replays those payloads through the real `ec hook handle`
# against a throwaway `ec init`-ed repository and asserts on the resulting
# `turns` rows — proving the bridge, not just the shim, delivers real data.
#
# Scenario 1 (main): a full turn with one tool call — asserts non-empty
#   user_message and the expected tools_used.
# Scenario 2 (dedup-genuine-repeat): a byte-identical prompt submitted as two
#   separate turns (turn_end between them) must produce TWO completed turns.
#   Regression guard for the before_agent_start dedup map: it must clear on
#   turn_end, or a legitimate repeat ("continue", "yes") is silently dropped.
# Scenario 3 (dedup-retry-collapse): a byte-identical prompt re-fired before
#   turn_end (the retry re-fire case extensions.md documents) must collapse
#   to ONE turn.
# Scenario 4 (no-ec-on-PATH): when `ec` is absent, spawn fails asynchronously
#   (ENOENT) and `child.stdin.end()` can race with the dead pipe; the stdin
#   'error' listener must absorb it so the driver exits cleanly instead of
#   crashing with an unhandled 'error' event.
# Scenario 5 (install-fresh-agent-dir): install.sh must complete on a fresh
#   PI_CODING_AGENT_DIR where $AGENT_DIR/extensions does not exist yet (bare
#   `find` exits non-zero under set -euo pipefail and would abort the script
#   before the success/restart messages).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Captures are numbered by a counter file so replay follows emission order.
# No locking needed: the extension serializes hook spawns per session, so the
# shim never runs concurrently with itself.
make_fake_ec() {
  local fakebin="$1" capture_dir="$2"
  cat > "$fakebin/ec" <<EOF
#!/usr/bin/env bash
counter="$capture_dir/.next"
n=\$(cat "\$counter" 2>/dev/null || echo 0)
printf '%d' "\$((n + 1))" > "\$counter"
f="$capture_dir/\$(printf '%03d' "\$n").json"
cat > "\$f"
hook=\$(jq -r .hook "\$f" 2>/dev/null)
case "\$hook" in
  UserPromptSubmit) echo '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"note"}}' ;;
  SessionStart) echo "plain note" ;;
  *) echo "" ;;
esac
EOF
  chmod +x "$fakebin/ec"
}

# Runs one scenario: drives $drive_script against a throwaway repo, replays
# captures in emission order, then hands the resulting turns rows (ordered by
# id) as JSON to $assert_script via argv[2] for scenario-specific assertions.
run_scenario() {
  local name="$1" drive_script="$2" expected_captures="$3" assert_script="$4"
  local work capture_dir fakebin repo session_id count result

  work=$(mktemp -d)
  capture_dir="$work/captures"
  fakebin="$work/fakebin"
  repo="$work/repo"
  mkdir -p "$capture_dir" "$fakebin" "$repo"

  make_fake_ec "$fakebin" "$capture_dir"
  printf '%s' "$drive_script" > "$work/drive.mjs"

  (cd "$repo" && git init -q && git config user.email t@example.com && git config user.name Test && git commit --allow-empty -q -m init)
  (cd "$repo" && ec init >/dev/null 2>&1)

  session_id="verify-$name-$(date +%s)-$$"
  PATH="$fakebin:$PATH" bun "$work/drive.mjs" "$SRC_DIR" "$repo" "$session_id"

  count=$(find "$capture_dir" -type f -name '*.json' | wc -l | tr -d ' ')
  if [[ "$count" != "$expected_captures" ]]; then
    echo "FAIL[$name]: expected $expected_captures captured payloads, got $count" >&2
    exit 1
  fi

  for f in "$capture_dir"/*.json; do   # zero-padded names: glob order == emission order
    hook=$(jq -r .hook "$f")
    ec hook handle --type "$hook" < "$f" >/dev/null
  done

  result=$(uv run --project "$SRC_DIR/../.." python -c "
import sqlite3, json
conn = sqlite3.connect('$repo/.entirecontext/db/local.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT user_message, tools_used, turn_status FROM turns WHERE session_id = ? ORDER BY id', ('$session_id',)).fetchall()
print(json.dumps([dict(r) for r in rows]))
")

  echo "[$name] captures=$count result=$result"
  python3 -c "$assert_script" "$name" "$result"

  rm -rf "$work"
}

DRIVE_PRELUDE='const [srcDir, cwd, sessionId] = process.argv.slice(2);
const mod = await import(`${srcDir}/extension/index.ts?t=${Date.now()}`);
const handlers = {};
const pi = {
  setLabel: () => {},
  getSessionName: () => sessionId,
  sendMessage: () => {},
  on: (event, handler) => { handlers[event] = handler; },
  logger: { warn: (m) => console.error(m) },
};
mod.default(pi);
const ctx = { cwd, sessionManager: { getSessionId: () => sessionId } };
await handlers.session_start({}, ctx);
'

# Scenario 1: one full turn with a tool call. Payloads: SessionStart, UPS,
# PostToolUse, Stop, SessionEnd = 5.
MAIN_DRIVE="$DRIVE_PRELUDE"'
await handlers.before_agent_start({ prompt: "verify harness prompt" }, ctx);
handlers.tool_result({ toolName: "bash", input: { command: "echo hi" } }, ctx);
handlers.turn_end({}, ctx);
await handlers.session_shutdown({}, ctx);
'
MAIN_ASSERT='
import sys, json
name, raw = sys.argv[1], sys.argv[2]
rows = json.loads(raw)
assert len(rows) == 1, f"FAIL[{name}]: expected 1 turn, got {rows}"
row = rows[0]
assert row["user_message"] == "verify harness prompt", f"FAIL[{name}]: {row}"
assert json.loads(row["tools_used"]) == ["bash"], f"FAIL[{name}]: {row}"
assert row["turn_status"] == "completed", f"FAIL[{name}]: {row}"
print(f"PASS[{name}]")
'

# Scenario 2: identical prompt as two genuine turns (turn_end between them).
# Payloads: SessionStart, UPS, Stop, UPS, Stop, SessionEnd = 6.
DEDUP_REPEAT_DRIVE="$DRIVE_PRELUDE"'
await handlers.before_agent_start({ prompt: "same prompt" }, ctx);
handlers.turn_end({}, ctx);
await handlers.before_agent_start({ prompt: "same prompt" }, ctx);
handlers.turn_end({}, ctx);
await handlers.session_shutdown({}, ctx);
'
DEDUP_REPEAT_ASSERT='
import sys, json
name, raw = sys.argv[1], sys.argv[2]
rows = json.loads(raw)
assert len(rows) == 2, f"FAIL[{name}]: expected 2 turns (genuine repeat), got {rows}"
for row in rows:
    assert row["user_message"] == "same prompt", f"FAIL[{name}]: {rows}"
    assert row["turn_status"] == "completed", f"FAIL[{name}]: {rows}"
print(f"PASS[{name}]")
'

# Scenario 3: identical prompt re-fired before turn_end (retry re-fire).
# Payloads: SessionStart, UPS, Stop, SessionEnd = 4.
DEDUP_RETRY_DRIVE="$DRIVE_PRELUDE"'
await handlers.before_agent_start({ prompt: "same prompt" }, ctx);
await handlers.before_agent_start({ prompt: "same prompt" }, ctx);
handlers.turn_end({}, ctx);
await handlers.session_shutdown({}, ctx);
'
DEDUP_RETRY_ASSERT='
import sys, json
name, raw = sys.argv[1], sys.argv[2]
rows = json.loads(raw)
assert len(rows) == 1, f"FAIL[{name}]: expected 1 turn (retry collapse), got {rows}"
row = rows[0]
assert row["user_message"] == "same prompt", f"FAIL[{name}]: {row}"
assert row["turn_status"] == "completed", f"FAIL[{name}]: {row}"
print(f"PASS[{name}]")
'

run_scenario main "$MAIN_DRIVE" 5 "$MAIN_ASSERT"
run_scenario dedup-genuine-repeat "$DEDUP_REPEAT_DRIVE" 6 "$DEDUP_REPEAT_ASSERT"
run_scenario dedup-retry-collapse "$DEDUP_RETRY_DRIVE" 4 "$DEDUP_RETRY_ASSERT"

# Scenario 4: `ec` dies instantly. `child.stdin.end()` racing the dead pipe
# emits EPIPE on the stdin stream; without the 'error' listener the Node host
# crashes with an unhandled 'error' event. Crash-mode evidence: 5/5 under
# plain node; bun does not propagate stdin 'error' to an uncaughtException in
# 10/10 probes (100KB payload, closed fd, delayed write), so this scenario
# asserts the survival contract but cannot fail deterministically pre-fix
# under bun.
NO_EC_DIR=$(mktemp -d)
mkdir -p "$NO_EC_DIR/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "$NO_EC_DIR/bin/ec"
chmod +x "$NO_EC_DIR/bin/ec"
NO_EC_DRIVE="$DRIVE_PRELUDE"'
const big = "x".repeat(100 * 1024); // exceeds pipe buffer: write must hit the dead pipe
await handlers.before_agent_start({ prompt: "ec dies instantly", tool_input: { data: big } }, ctx);
handlers.tool_result({ toolName: "bash", input: { command: "echo hi", data: big } }, ctx);
handlers.turn_end({}, ctx);
await handlers.session_shutdown({}, ctx);
'
printf '%s' "$NO_EC_DRIVE" > "$NO_EC_DIR/drive.mjs"
PATH="$NO_EC_DIR/bin:$(dirname "$(command -v bun)")" bun "$NO_EC_DIR/drive.mjs" "$SRC_DIR" /tmp "noec-$(date +%s)-$$" \
  2>"$NO_EC_DIR/stderr.log"
driver_status=$?
if [[ "$driver_status" != "0" ]]; then
  echo "FAIL[no-ec-on-PATH]: driver exited $driver_status (host crash?)" >&2
  tail -5 "$NO_EC_DIR/stderr.log" >&2
  rm -rf "$NO_EC_DIR"
  exit 1
fi
echo "PASS[no-ec-on-PATH]"
rm -rf "$NO_EC_DIR"

# Scenario 5: install.sh on a fresh agent dir with no extensions/ subdirectory.
INSTALL_DIR=$(mktemp -d)
AGENT_DIR="$INSTALL_DIR/agent"
mkdir -p "$AGENT_DIR" "$INSTALL_DIR/bin"
cat > "$INSTALL_DIR/bin/omp" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$INSTALL_DIR/bin/omp"
if ! PATH="$INSTALL_DIR/bin:$PATH" PI_CODING_AGENT_DIR="$AGENT_DIR" \
    "$SRC_DIR/install.sh" >/dev/null 2>&1; then
  echo "FAIL[install-fresh-agent-dir]: install.sh aborted on fresh agent dir" >&2
  rm -rf "$INSTALL_DIR"
  exit 1
fi
echo "PASS[install-fresh-agent-dir]"
rm -rf "$INSTALL_DIR"

echo "ALL PASS"
