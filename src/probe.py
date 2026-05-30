"""Source #2: empirically test a model's knowledge cutoff via walk-back.

Algorithm (per the task spec):
  * Walk months from the most recent backwards in time.
  * For each month ask ALL of its questions (4 per month); the month is "passed"
    only if EVERY question is answered correctly. If some but not all are
    correct the month is "partial"; if none are correct it is "fail".
  * The first passed month is a candidate cutoff. We require TWO consecutive
    passed months (a passed month immediately followed, going back in time, by
    another passed month) to confirm -- this guards against a lucky single guess.
  * The confirmed cutoff is the MOST RECENT of those two consecutive months.
  * Any non-pass month (partial or fail) resets the streak.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .grader import Grader
from .openrouter import OpenRouter

PROBE_SYSTEM = (
    "You are answering a short factual quiz about real-world news events. "
    "Reply with ONLY the specific name, team, place, or number requested -- a few "
    "words at most, no explanation. Do not browse or speculate. If you genuinely do "
    "not know because the event is after your knowledge cutoff, reply exactly: "
    "I DON'T KNOW."
)


@dataclass
class MonthResult:
    month: str
    passed: bool
    details: list[dict] = field(default_factory=list)
    n_correct: int = 0
    n_total: int = 0

    @property
    def status(self) -> str:
        if self.passed:
            return "pass"
        if self.n_correct > 0:
            return "partial"
        return "fail"


@dataclass
class ProbeResult:
    model: str
    tested_cutoff: str | None
    months_tested: list[MonthResult] = field(default_factory=list)
    note: str = ""


def questions_for_month(month_entry: dict) -> list[dict]:
    """All questions for the month (the method uses every one -- 4 per month)."""
    return list(month_entry["questions"])


def probe_model(
    client: OpenRouter,
    grader: Grader,
    model: str,
    months: list[str],
    questions: dict,
    require_consecutive: int = 2,
    verbose: bool = False,
) -> ProbeResult:
    """months: list ordered most-recent-first. questions: the 'months' dict."""
    streak = 0
    candidate = None
    results: list[MonthResult] = []

    for month in months:
        entry = questions[month]
        qs = questions_for_month(entry)
        if not qs:
            # no questions for this month; skip it
            continue

        details = []
        n_correct = 0
        for q in qs:
            res = client.chat(
                model,
                [
                    {"role": "system", "content": PROBE_SYSTEM},
                    {"role": "user", "content": q["q"]},
                ],
            )
            if not res.ok:
                details.append({"id": q["id"], "ok": False, "reply": "", "error": res.error})
                continue
            correct = grader.grade(q["q"], q["a"], res.text, q.get("accept", []))
            details.append(
                {"id": q["id"], "ok": correct, "reply": res.text[:300]}
            )
            if correct:
                n_correct += 1

        n_total = len(qs)
        passed = n_correct == n_total  # require ALL questions correct
        results.append(MonthResult(month, passed, details, n_correct, n_total))
        if verbose:
            mark = "PASS" if passed else ("partial" if n_correct else "fail")
            print(f"    {month}: {mark} ({n_correct}/{n_total})")

        if passed:
            if streak == 0:
                candidate = month  # most-recent month of a potential run
            streak += 1
            if streak >= require_consecutive:
                return ProbeResult(model, candidate, results)
        else:
            streak = 0
            candidate = None

    # Reached the end without a confirmed consecutive run.
    note = ""
    tested = None
    if candidate is not None and streak >= 1:
        # passed the oldest month(s) but couldn't confirm a second below it
        tested = candidate
        note = "unconfirmed (hit oldest tested month); cutoff may be older"
    elif not any(r.passed for r in results):
        note = "no tested month passed; cutoff older than oldest question, or model refused"
    return ProbeResult(model, tested, results, note)
