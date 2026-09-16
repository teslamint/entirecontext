/* EntireContext plugin for omp (Oh My Pi).
 *
 * Bridges omp lifecycle events to EntireContext capture hooks by invoking
 *   ec hook handle --type <HookType>
 * with a JSON payload on stdin — the same protocol Claude Code uses.
 *
 * Event mapping (right column = key read by src/entirecontext/hooks/*):
 *   session_start      -> SessionStart      session_id, cwd, source
 *   before_agent_start -> UserPromptSubmit  session_id, cwd, prompt
 *   tool_result        -> PostToolUse       session_id, cwd, tool_name, tool_input
 *   turn_end           -> Stop              session_id, cwd
 *   session_shutdown   -> SessionEnd        session_id, cwd
 *
 * `tool_result` (not `tool_call`) maps to PostToolUse: `tool_call` is
 * pre-execution and carries no result; `tool_result` is the documented
 * post-execution event with `toolName`/`input`.
 *
 * Per-session ordering: EC's turn state machine requires PostToolUse to land
 * before the Stop that completes the turn (turn_capture.py on_tool_use only
 * updates an 'in_progress' turn; on_stop flips it to 'completed'). Every hook
 * call for a session is therefore chained through one FIFO queue instead of
 * fired independently, so a fast Stop can never race ahead of a slower
 * PostToolUse for the same turn.
 *
 * Context EC surfaces on stdout is fed back into the session as a `custom`
 * message: SessionStart prints plain text; UserPromptSubmit prints a
 * `{"hookSpecificOutput":{"additionalContext": "..."}}` envelope
 * (handler.py:373-381) that must be parsed, not used as raw content.
 *
 * Types are declared locally on purpose: the plugin must typecheck without the
 * host package (@oh-my-pi/pi-coding-agent) installed.
 */

import type { ChildProcess } from "node:child_process";
import { spawn } from "node:child_process";
import { cwd as processCwd } from "node:process";

const EC_COMMAND = "ec";
/** EC's own hook budget. A slower hook is abandoned rather than stalling a turn. */
const HOOK_TIMEOUT_MS = 3000;
const CUSTOM_TYPE = "com.entirecontext.context";

interface SessionManager {
  getSessionId?(): unknown;
}

interface ExtensionContextLike {
  cwd?: string;
  sessionManager?: SessionManager;
}

interface CustomMessage {
  customType: string;
  content: string;
  display: boolean;
  attribution: "agent" | "user";
}

interface ExtensionHost {
  getSessionName?(): unknown;
  setLabel?(label: string): void;
  sendMessage?(message: CustomMessage, options?: { deliverAs?: string }): unknown;
  on(
    event: string,
    handler: (
      event: unknown,
      ctx: ExtensionContextLike,
    ) => unknown | Promise<unknown>,
  ): void;
  logger?: { warn?(message: string): void };
}

function warn(pi: ExtensionHost, message: string): void {
  if (pi.logger?.warn) {
    pi.logger.warn(`[entirecontext] ${message}`);
    return;
  }
  console.warn(`[entirecontext] ${message}`);
}

function sessionIdOf(pi: ExtensionHost, ctx: ExtensionContextLike): string {
  const fromCtx = ctx.sessionManager?.getSessionId?.();
  if (typeof fromCtx === "string" && fromCtx) return fromCtx;
  const fromPi = pi.getSessionName?.();
  if (typeof fromPi === "string" && fromPi) return fromPi;
  return "";
}

/** The session's own working directory, falling back to the process cwd. */
function cwdOf(ctx: ExtensionContextLike): string {
  return typeof ctx.cwd === "string" && ctx.cwd ? ctx.cwd : processCwd();
}

/** Type guard: narrow an unknown event payload field to a plain record. */
function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

/** Reads the first present key across camelCase/snake_case event field variants. */
function pick(event: unknown, ...keys: string[]): unknown {
  const obj = asRecord(event);
  for (const key of keys) {
    if (key in obj) return obj[key];
  }
  return undefined;
}

/**
 * Run one EC hook. Resolves with the hook's raw stdout (possibly empty).
 * Never rejects: a missing `ec`, a crash, or a timeout resolves "".
 */
function runEcHook(
  pi: ExtensionHost,
  type: string,
  data: Record<string, unknown>,
): Promise<string> {
  const { promise, resolve } = Promise.withResolvers<string>();
  let settled = false;
  const finish = (out: string) => {
    if (settled) return;
    settled = true;
    resolve(out);
  };

  const workDir = typeof data.cwd === "string" && data.cwd ? data.cwd : processCwd();

  let child: ChildProcess;
  try {
    child = spawn(EC_COMMAND, ["hook", "handle", "--type", type], {
      cwd: workDir,
      stdio: ["pipe", "pipe", "pipe"],
    });
  } catch (err) {
    warn(pi, `spawn ${type} failed: ${(err as Error).message}`);
    finish("");
    return promise;
  }

  const timer = setTimeout(() => {
    child.kill("SIGKILL");
    finish("");
  }, HOOK_TIMEOUT_MS);
  timer.unref?.();

  let stdout = "";
  // A killed/exited child can emit EPIPE (or other) errors on stdin
  // asynchronously, after the try/catch around `stdin.end()` below has
  // already returned; without a listener that crashes the omp host.
  child.stdin?.on("error", (err: Error) => {
    warn(pi, `writing ${type} payload failed: ${err.message}`);
    clearTimeout(timer);
    finish("");
  });
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    stdout += chunk;
  });
  // EC writes diagnostics to stderr; keep them out of the TUI.
  child.stderr?.resume();

  child.on("error", (err: Error) => {
    clearTimeout(timer);
    warn(pi, `hook ${type} failed: ${err.message}`);
    finish("");
  });
  child.on("close", () => {
    clearTimeout(timer);
    finish(stdout.trim());
  });

  try {
    child.stdin?.end(JSON.stringify({ hook: type, ...data }));
  } catch (err) {
    warn(pi, `writing ${type} payload failed: ${(err as Error).message}`);
    child.kill("SIGKILL");
    clearTimeout(timer);
    finish("");
  }

  return promise;
}

/** Per-session FIFO so PostToolUse always reaches `ec` before the Stop that completes the turn. */
const sessionQueues = new Map<string, Promise<string>>();

/** Chain one hook call onto its session's queue and return its surfaced stdout. */
function queueHook(
  pi: ExtensionHost,
  sessionId: string,
  type: string,
  data: Record<string, unknown>,
): Promise<string> {
  const prior = sessionQueues.get(sessionId) ?? Promise.resolve("");
  const next = prior.then(() => runEcHook(pi, type, data));
  sessionQueues.set(sessionId, next);
  return next;
}

/** Chain a hook call without making the caller wait on its result. */
function emitQueuedHook(
  pi: ExtensionHost,
  sessionId: string,
  type: string,
  data: Record<string, unknown>,
): void {
  void queueHook(pi, sessionId, type, data);
}

/**
 * UserPromptSubmit prints a hookSpecificOutput envelope
 * (`{"hookSpecificOutput":{"additionalContext": "..."}}`); other hooks print
 * plain text. Returns "" when there is nothing to surface.
 */
function extractAdditionalContext(type: string, raw: string): string {
  if (!raw) return "";
  if (type !== "UserPromptSubmit") return raw;
  try {
    const parsed = JSON.parse(raw) as {
      hookSpecificOutput?: { additionalContext?: unknown };
    };
    const additionalContext = parsed.hookSpecificOutput?.additionalContext;
    return typeof additionalContext === "string" ? additionalContext : "";
  } catch {
    return "";
  }
}

export default function entirecontext(pi: ExtensionHost): void {
  pi.setLabel?.("EntireContext");

  // Guards the `before_agent_start` re-fire case (extensions.md: a source-base
  // retry or resumed delivery can replay the same submission with no rollback
  // of prior side effects) so a retried prompt doesn't create a duplicate turn.
  const lastPromptBySession = new Map<string, string>();

  pi.on("session_start", async (_event, ctx) => {
    const sessionId = sessionIdOf(pi, ctx);
    const surfaced = await queueHook(pi, sessionId, "SessionStart", {
      session_id: sessionId,
      cwd: cwdOf(ctx),
      source: "startup",
      timestamp: new Date().toISOString(),
    });
    if (!surfaced) return;
    try {
      // Session start has no prompt to attach to; land it on the next turn.
      pi.sendMessage?.(
        { customType: CUSTOM_TYPE, content: surfaced, display: true, attribution: "agent" },
        { deliverAs: "nextTurn" },
      );
    } catch (err) {
      warn(pi, `injecting session context failed: ${(err as Error).message}`);
    }
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const sessionId = sessionIdOf(pi, ctx);
    const promptValue = pick(event, "prompt");
    const prompt = typeof promptValue === "string" ? promptValue : "";

    if (lastPromptBySession.get(sessionId) === prompt) return;
    lastPromptBySession.set(sessionId, prompt);

    const raw = await queueHook(pi, sessionId, "UserPromptSubmit", {
      session_id: sessionId,
      cwd: cwdOf(ctx),
      prompt,
      timestamp: new Date().toISOString(),
    });
    const surfaced = extractAdditionalContext("UserPromptSubmit", raw);
    if (!surfaced) return;
    return {
      message: { customType: CUSTOM_TYPE, content: surfaced, display: true, attribution: "agent" },
    };
  });

  pi.on("tool_result", (event, ctx) => {
    const sessionId = sessionIdOf(pi, ctx);
    const toolNameValue = pick(event, "toolName", "tool_name");
    emitQueuedHook(pi, sessionId, "PostToolUse", {
      session_id: sessionId,
      cwd: cwdOf(ctx),
      tool_name: typeof toolNameValue === "string" ? toolNameValue : "",
      tool_input: asRecord(pick(event, "input", "tool_input")),
      timestamp: new Date().toISOString(),
    });
  });

  pi.on("turn_end", (_event, ctx) => {
    const sessionId = sessionIdOf(pi, ctx);
    // The retry window closes once the turn has run: a byte-identical prompt
    // sent after this point ("continue", "yes") is a genuine new turn.
    lastPromptBySession.delete(sessionId);
    emitQueuedHook(pi, sessionId, "Stop", {
      session_id: sessionId,
      cwd: cwdOf(ctx),
      timestamp: new Date().toISOString(),
    });
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    const sessionId = sessionIdOf(pi, ctx);
    // Awaited (not fire-and-forget): SessionEnd triggers summaries and
    // auto-sync/distill, and is the hook most likely to be cut off by process
    // exit if left unawaited. Draining the queue first also ensures any
    // trailing PostToolUse/Stop from this turn are sent before SessionEnd.
    await queueHook(pi, sessionId, "SessionEnd", {
      session_id: sessionId,
      cwd: cwdOf(ctx),
      timestamp: new Date().toISOString(),
    });
    sessionQueues.delete(sessionId);
    lastPromptBySession.delete(sessionId);
  });
}
