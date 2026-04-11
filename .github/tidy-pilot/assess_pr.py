"""Tidy Pilot PR assessment script for GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def call_llm(system: str, user: str) -> dict:
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
    req = Request(
        base_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urlopen(req) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


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

    # Read inputs
    diff = Path("/tmp/pr.diff").read_text(encoding="utf-8", errors="replace")
    max_diff = 12000
    if len(diff) > max_diff:
        diff = diff[:max_diff] + "\n\n... (diff truncated)"

    roadmap = ""
    if Path("ROADMAP.md").exists():
        roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")

    lessons = ""
    if Path("LESSONS.md").exists():
        lessons = Path("LESSONS.md").read_text(encoding="utf-8")

    claude_md = ""
    if Path("CLAUDE.md").exists():
        claude_md = Path("CLAUDE.md").read_text(encoding="utf-8")

    # Build prompt
    user_prompt = f"## PR #{args.pr_number}: {args.pr_title}\n\n"
    if roadmap:
        user_prompt += f"### ROADMAP\n```markdown\n{roadmap}\n```\n\n"
    if lessons:
        user_prompt += f"### LESSONS LEARNED\n```markdown\n{lessons}\n```\n\n"
    if claude_md:
        user_prompt += f"### PROJECT CONVENTIONS (CLAUDE.md)\n```markdown\n{claude_md}\n```\n\n"
    user_prompt += f"### DIFF\n```diff\n{diff}\n```"

    # Call LLM
    print(f"Analyzing PR #{args.pr_number}: {args.pr_title}")
    result = call_llm(SYSTEM_PROMPT, user_prompt)

    verdict = result.get("verdict", "neutral")
    verdict_icons = {"expand": "\U0001f7e2", "narrow": "\U0001f534", "neutral": "\u26aa"}
    icon = verdict_icons.get(verdict, "")

    # Skip comment on neutral (configurable)
    if verdict == "neutral" and os.environ.get("COMMENT_ON_NEUTRAL", "false") != "true":
        print("Verdict: neutral — skipping comment.")
        return

    # Build comment
    comment = f"""{COMMENT_MARKER}
## \U0001f9f9 Tidy Pilot — Futures Assessment

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
