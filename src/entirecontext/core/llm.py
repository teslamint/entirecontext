"""LLM backend abstraction for futures assessment."""

from __future__ import annotations

import json
import os
import subprocess
from urllib.request import Request, urlopen


class LLMBackend:
    """Base class for LLM backends."""

    def __init__(self, model: str | None = None):
        self.model = model

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class OpenAIBackend(LLMBackend):
    """OpenAI API backend. Requires OPENAI_API_KEY env var."""

    def __init__(self, model: str | None = None):
        super().__init__(model or "gpt-4o-mini")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set")
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }).encode()
        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urlopen(req) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


class CLIBackend(LLMBackend):
    """CLI subprocess backend for codex, claude, etc."""

    COMMANDS = {
        "codex": lambda prompt, model: ["codex", "exec", "-"],
        "claude": lambda prompt, model: ["claude", "-p", prompt, "--output-format", "json"],
    }

    def __init__(self, command: str = "codex", model: str | None = None):
        super().__init__(model)
        self.command = command

    def complete(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n---\n\n{user}"
        cmd_fn = self.COMMANDS.get(self.command)
        if cmd_fn is None:
            # Generic: just pass prompt as argument
            cmd = [self.command, prompt]
        else:
            cmd = cmd_fn(prompt, self.model)

        stdin_input = prompt if self.command == "codex" else None
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, input=stdin_input)
        if result.returncode != 0:
            raise RuntimeError(f"{self.command} failed (exit {result.returncode}): {result.stderr}")

        output = result.stdout.strip()
        # claude --output-format json wraps in JSON
        if self.command == "claude":
            try:
                data = json.loads(output)
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
            except json.JSONDecodeError:
                pass
        return output


class OllamaBackend(LLMBackend):
    """Ollama local model backend."""

    def __init__(self, model: str | None = None, base_url: str = "http://localhost:11434"):
        super().__init__(model or "llama3")
        self.base_url = base_url

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }).encode()
        req = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as resp:
            data = json.loads(resp.read())
        return data["message"]["content"]


BACKENDS = {
    "openai": OpenAIBackend,
    "codex": lambda model=None: CLIBackend("codex", model),
    "claude": lambda model=None: CLIBackend("claude", model),
    "ollama": OllamaBackend,
}


def get_backend(name: str = "openai", model: str | None = None) -> LLMBackend:
    """Get an LLM backend by name."""
    factory = BACKENDS.get(name)
    if factory is None:
        available = ", ".join(BACKENDS.keys())
        raise ValueError(f"Unknown backend '{name}'. Available: {available}")
    return factory(model=model)
