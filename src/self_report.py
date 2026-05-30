"""Source #3 (self-report): ask the model directly for its own knowledge cutoff.

This is a noisy signal -- models often parrot their *base* model's cutoff, give a
year with no month, or refuse outright -- but it's interesting precisely because
it so often disagrees with the provider's published claim. We surface it as a
contrast column / chart bar, not as ground truth.
"""
from __future__ import annotations

from .openrouter import OpenRouter
from .public_cutoffs import _normalize_ym

SELF_REPORT_PROMPT = (
    "What is your knowledge cutoff date? Please answer with the month and the "
    "four-digit year, in the format 'Month YYYY'."
)


def ask_self_reported_cutoff(
    client: OpenRouter, model: str, max_tokens: int = 120
) -> tuple[str | None, str | None, str | None]:
    """Return (raw_reply, normalized 'YYYY-MM' or None, error or None).

    The error string (when the call failed) doubles as a cheap reachability
    pre-flight: a 404 / "not found" means the model has no chat endpoint and the
    caller should skip the (expensive) walk-back probe entirely.
    """
    res = client.chat(
        model,
        [{"role": "user", "content": SELF_REPORT_PROMPT}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    if not res.ok:
        return None, None, res.error
    raw = " ".join((res.text or "").split())
    return (raw or None), _normalize_ym(raw), None


def is_unreachable(error: str | None) -> bool:
    """True if the error indicates the model has no usable chat endpoint."""
    if not error:
        return False
    low = error.lower()
    return "404" in low or "not found" in low or "no endpoints" in low
