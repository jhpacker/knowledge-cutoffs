"""Grade a model's free-text answer against an expected answer.

Two layers:
  1. Keyword fallback: any string in the question's `accept` list appears in the
     reply (case-insensitive). Deterministic, no API cost.
  2. LLM judge: a strong, cheap model decides semantic equivalence. The judge is
     GIVEN the expected answer, so it only checks equivalence and does not rely
     on its own world knowledge.

A reply is correct if the judge says CORRECT (when enabled), else the keyword
fallback decides. Refusals / "I don't know" count as incorrect.
"""
from __future__ import annotations

import re

from .openrouter import OpenRouter

REFUSAL_MARKERS = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "i cannot determine", "i can't determine", "unable to determine",
    "no knowledge", "after my", "beyond my", "my training", "knowledge cutoff",
    "i don't have information", "not aware of", "cannot answer",
]

JUDGE_SYSTEM = (
    "You are a strict grader. You are given a QUESTION, the EXPECTED answer, and a "
    "model's ANSWER. Decide whether the ANSWER is correct, i.e. it clearly contains "
    "or matches the EXPECTED answer's key fact. Ignore extra commentary, hedging, or "
    "style. If the answer is a refusal, says it doesn't know, or names the wrong "
    "entity, it is incorrect. Respond with exactly one word: CORRECT or INCORRECT."
)


def keyword_correct(reply: str, accept: list[str]) -> bool:
    low = reply.lower()
    return any(a.lower() in low for a in accept if a)


def looks_like_refusal(reply: str) -> bool:
    low = reply.lower()
    return any(m in low for m in REFUSAL_MARKERS)


class Grader:
    def __init__(self, client: OpenRouter | None = None, judge_model: str | None = None):
        self.client = client
        self.judge_model = judge_model  # None => keyword-only grading

    def grade(self, question: str, expected: str, reply: str, accept: list[str]) -> bool:
        if not reply.strip():
            return False
        # Strong keyword hit is decisive (cheap, avoids a judge call).
        kw = keyword_correct(reply, accept)
        if self.judge_model is None or self.client is None:
            return kw and not looks_like_refusal(reply)
        if kw and not looks_like_refusal(reply):
            return True
        # Otherwise ask the judge.
        user = (
            f"QUESTION: {question}\n"
            f"EXPECTED: {expected}\n"
            f"ANSWER: {reply}\n\n"
            "Verdict (CORRECT or INCORRECT):"
        )
        res = self.client.chat(
            self.judge_model,
            [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        if not res.ok:
            return kw  # fall back to keyword if judge unavailable
        verdict = re.sub(r"[^a-z]", "", res.text.lower())
        return verdict.startswith("correct")
