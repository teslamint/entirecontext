"""Shared LLM token estimation.

Single canonical estimator so injection budgets and token-savings telemetry
measure payloads the same way. Uses tiktoken (cl100k_base) when available,
falling back to a utf-8 byte heuristic (~3 bytes/token) that matches the
historical fallback in ``core/decision_prompt_surfacing``.
"""

from __future__ import annotations


def _load_default_encoding() -> object | None:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_ENCODING = _load_default_encoding()

_UNSET = object()


def estimate_tokens(text: str, *, encoding: object = _UNSET) -> int:
    """Estimate the LLM token count of ``text``.

    ``encoding`` lets callers inject their own (possibly monkeypatched)
    tiktoken encoding; the module-level cl100k_base encoding is used by
    default. ``None`` forces the byte-heuristic fallback.
    """
    enc = _ENCODING if encoding is _UNSET else encoding
    if enc is not None:
        try:
            return max(1, len(enc.encode(text, disallowed_special=())))  # type: ignore[attr-defined]
        except Exception:
            pass
    return max(1, len(text.encode("utf-8")) // 3)
