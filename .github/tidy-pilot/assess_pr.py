"""Tidy Pilot PR assessment script for GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from pathlib import Path
from urllib.request import Request, urlopen

SYSTEM_PROMPT = """You are a futures analyst grounded in Kent Beck's "Tidy First" philosophy.
You evaluate code changes through the lens of software design options:
- **expand**: the change increases future options (good structure, reversibility, new capabilities)
- **narrow**: the change reduces future options (tight coupling, irreversible decisions, tech debt)
- **neutral**: the change neither significantly expands nor narrows future options

Analyze the given diff against the project roadmap and past lessons.
Respond with a JSON object (no markdown fences) with these fields:
- verdict: "expand" | "narrow" | "neutral"
- impact_summary: one-sentence summary of the change's impact on future options
- roadmap_alignment: how this change aligns with the roadmap
- tidy_suggestion: actionable suggestion grounded in specific project files, structures, or patterns observed in the diff. Do not suggest actions referencing structures that are not present in the project context."""

COMMENT_MARKER = "<!-- tidy-pilot:sticky-comment -->"

# Character budgets — chosen to stay under typical API payload limits.
MAX_CONTEXT_CHARS = 4_000   # per context section (roadmap, lessons, claude_md)
MAX_CHUNK_DIFF_CHARS = 8_000  # per diff chunk sent to LLM
MAX_CHUNKS = 5              # cap on total API calls; chunk size grows proportionally if exceeded


def call_llm(system: str, user: str, *, max_retries: int = 3) -> dict:
    backend = os.environ.get("TIDY_PILOT_BACKEND", "github")
    if backend == "github":
        api_key = os.environ.get("GITHUB_TOKEN", "")
        base_url = "https://models.github.ai/inference/chat/completions"
        model = os.environ.get("TIDY_PILOT_MODEL", "openai/gpt-4o-mini")
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = "https://api.openai.com/v1/chat/completions"
        model = os.environ.get("TIDY_PILOT_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError(f"API key not set for backend '{backend}'")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
    ).encode()

    for attempt in range(max_retries + 1):
        req = Request(
            base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s
                print(f"  429 rate limit — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                raise

    content = data["choices"][0]["message"]["content"]
    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def split_diff_by_file(diff: str) -> list[str]:
    """Split a unified diff into per-file sections on 'diff --git' boundaries."""
    sections: list[str] = []
    current: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git") and current:
            sections.append("".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("".join(current))
    return sections


def chunk_diff(diff: str, max_chars: int, *, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """Group per-file diff sections into at most max_chunks chunks.

    Files are distributed evenly across chunks (ceiling division). Each
    individual file diff is hard-truncated to max_chars so no single chunk
    blows the API payload limit.
    """
    file_sections = split_diff_by_file(diff)
    if not file_sections:
        return [""]

    n = len(file_sections)
    # Ceiling division: how many files per chunk to stay within max_chunks.
    files_per_chunk = max(1, -(-n // max_chunks))

    chunks: list[str] = []
    for i in range(0, n, files_per_chunk):
        parts = []
        for section in file_sections[i : i + files_per_chunk]:
            if len(section) > max_chars:
                section = section[:max_chars] + "\n... (file diff truncated)\n"
            parts.append(section)
        chunks.append("".join(parts))
    return chunks


def merge_results(results: list[dict]) -> dict:
    """Merge per-chunk LLM results into a single final assessment.

    Verdict escalation: narrow > neutral > expand (conservative — any narrow
    chunk makes the whole PR narrow).
    """
    if len(results) == 1:
        return results[0]
    priority = {"narrow": 2, "neutral": 1, "expand": 0}
    dominant = max(results, key=lambda r: priority.get(r.get("verdict", "neutral"), 1))
    impact_parts = [r["impact_summary"] for r in results if r.get("impact_summary")]
    suggestions = [r["tidy_suggestion"] for r in results if r.get("tidy_suggestion")]
    return {
        "verdict": dominant.get("verdict", "neutral"),
        "impact_summary": " | ".join(impact_parts[:2]),
        "roadmap_alignment": dominant.get("roadmap_alignment", "N/A"),
        "tidy_suggestion": suggestions[0] if suggestions else "N/A",
    }


def build_user_prompt(
    pr_number: int,
    pr_title: str,
    diff_chunk: str,
    roadmap: str,
    lessons: str,
    claude_md: str,
    chunk_index: int,
    total_chunks: int,
) -> str:
    header = f"## PR #{pr_number}: {pr_title}\n\n"
    if total_chunks > 1:
        header += f"_(Diff chunk {chunk_index + 1} of {total_chunks})_\n\n"
    prompt = header
    if roadmap:
        prompt += f"### ROADMAP\n```markdown\n{roadmap}\n```\n\n"
    if lessons:
        prompt += f"### LESSONS LEARNED\n```markdown\n{lessons}\n```\n\n"
    if claude_md:
        prompt += f"### PROJECT CONVENTIONS (CLAUDE.md)\n```markdown\n{claude_md}\n```\n\n"
    prompt += f"### DIFF\n```diff\n{diff_chunk}\n```"
    return prompt


def github_api_request(url: str, token: str, *, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method=method,
    )
    return urlopen(req)


def find_existing_comment_id(repo: str, pr_number: int, token: str) -> int | None:
    page = 1
    while True:
        with github_api_request(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}",
            token,
        ) as resp:
            comments = json.loads(resp.read())
        if not comments:
            return None
        for comment in comments:
            if COMMENT_MARKER in comment.get("body", ""):
                return comment["id"]
        page += 1


def comment_on_pr(repo: str, pr_number: int, body: str) -> None:
    token = os.environ["GITHUB_TOKEN"]
    comment_id = find_existing_comment_id(repo, pr_number, token)
    payload = {"body": body}
    if comment_id is None:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        method = "POST"
    else:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
        method = "PATCH"
    with github_api_request(url, token, method=method, payload=payload) as resp:
        if resp.status >= 300:
            print(f"GitHub API error: {resp.status}", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--pr-title", type=str, default="")
    parser.add_argument("--repo", type=str, required=True)
    args = parser.parse_args()

    diff = Path("/tmp/pr.diff").read_text(encoding="utf-8", errors="replace")

    def _read_truncated(path: str) -> str:
        p = Path(path)
        if not p.exists():
            return ""
        text = p.read_text(encoding="utf-8")
        if len(text) > MAX_CONTEXT_CHARS:
            text = text[:MAX_CONTEXT_CHARS] + "\n\n... (truncated)"
        return text

    roadmap = _read_truncated("ROADMAP.md")
    lessons = _read_truncated("LESSONS.md")
    claude_md = _read_truncated("CLAUDE.md")

    chunks = chunk_diff(diff, MAX_CHUNK_DIFF_CHARS)
    print(f"Analyzing PR #{args.pr_number}: {args.pr_title} ({len(chunks)} diff chunk(s))")

    results: list[dict] = []
    for i, chunk in enumerate(chunks):
        user_prompt = build_user_prompt(
            args.pr_number, args.pr_title, chunk,
            roadmap, lessons, claude_md,
            i, len(chunks),
        )
        print(f"  chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        result = call_llm(SYSTEM_PROMPT, user_prompt)
        results.append(result)

    result = merge_results(results)

    verdict = result.get("verdict", "neutral")
    verdict_icons = {"expand": "\U0001f7e2", "narrow": "\U0001f534", "neutral": "⚪"}
    icon = verdict_icons.get(verdict, "")

    if verdict == "neutral" and os.environ.get("COMMENT_ON_NEUTRAL", "false") != "true":
        print("Verdict: neutral — skipping comment.")
        return

    chunk_note = f" _(assessed across {len(chunks)} diff chunks)_" if len(chunks) > 1 else ""
    comment = f"""{COMMENT_MARKER}
## \U0001f9f9 Tidy Pilot — Futures Assessment{chunk_note}

**{icon} {verdict.upper()}**

**Impact:** {result.get("impact_summary", "N/A")}

**Roadmap alignment:** {result.get("roadmap_alignment", "N/A")}

**Suggestion:** {result.get("tidy_suggestion", "N/A")}

---
<sub>Powered by Tidy Pilot — analyzing futures, not just features</sub>"""

    comment_on_pr(args.repo, args.pr_number, comment)
    print(f"Comment posted: {icon} {verdict}")


if __name__ == "__main__":
    main()
