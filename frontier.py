#!/usr/bin/env python3
"""Build out/frontier.json: the newest model per frontier lab (Anthropic/OpenAI/
Google), then render it with `viz.py --brand`.

Rows already present in out/results.json are reused; any model not in there (e.g.
a release that post-dates the last full run) is probed fresh the same way main.py
does. Each row gets the model's release date (OpenRouter `created`).

Usage:
  python frontier.py                       # build out/frontier.json
  python viz.py --in out/frontier.json --labs all --brand \
                --out out/recency_frontier.png --title "Frontier models ..."
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from main import load_questions, release_date, usable_months
from src.grader import Grader
from src.openrouter import OpenRouter
from src.probe import probe_model
from src.public_cutoffs import (
    PublicCutoffLookup,
    fetch_repo_table,
    openrouter_published_cutoff,
)
from src.self_report import ask_self_reported_cutoff, is_unreachable

ROOT = Path(__file__).parent

# Newest model per frontier lab. Edit this to change the frontier set.
FRONTIER = [
    "openai/gpt-5.5",
    "google/gemini-3.5-flash",
    "anthropic/claude-opus-4.8",
]

# Provider-official claimed cutoffs not (yet) in the HaoooWang repo or OpenRouter's
# `knowledge_cutoff` field. For Anthropic we use the *Training Data* cut-off per
# the project convention. Source: Anthropic docs "Latest models comparison".
# https://platform.claude.com/docs/en/about-claude/models/overview
OFFICIAL_CUTOFFS = {
    "anthropic/claude-opus-4.8": "2026-01",
}


def probe_one(client, lookup, grader, months, questions, catalog, slug) -> dict:
    m = catalog.get(slug, {"id": slug, "name": slug})
    name = m.get("name") or slug
    self_raw, self_cut, self_err = ask_self_reported_cutoff(client, slug)
    if is_unreachable(self_err):
        print(f"  {slug}: UNREACHABLE ({self_err}); skipping probe")
        tested, note, detail = None, "no chat endpoint (404); probe skipped", []
    else:
        print(f"  {slug}: self-report {self_cut or '—'}; probing walk-back ...")
        res = probe_model(
            client, grader, slug, months, questions, verbose=True,
            progress=lambda mo, mk, nc, nt: print(f"      {mo}: {mk} ({nc}/{nt})"),
        )
        tested, note = res.tested_cutoff, res.note
        detail = [
            {"month": r.month, "status": r.status, "n_correct": r.n_correct, "n_total": r.n_total}
            for r in res.months_tested
        ]
    return {
        "model": slug, "name": name, "released": release_date(m),
        "repo_cutoff": lookup.match(m).cutoff,
        "openrouter_cutoff": openrouter_published_cutoff(m),
        "claimed_cutoff": OFFICIAL_CUTOFFS.get(slug),
        "self_reported_cutoff": self_cut, "self_reported_raw": self_raw,
        "tested_cutoff": tested,
        "partial_months": [d["month"] for d in detail if d["status"] == "partial"],
        "months_detail": detail, "note": note,
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    client = OpenRouter()
    catalog = {m.get("id"): m for m in client.list_models()}
    existing = {r["model"]: r for r in json.loads((ROOT / "out" / "results.json").read_text())}

    questions = load_questions()
    months = usable_months(questions)
    lookup = PublicCutoffLookup(fetch_repo_table())
    grader = Grader(client, None)  # keyword-only

    rows = []
    for slug in FRONTIER:
        if slug in existing:
            r = dict(existing[slug])
            r["released"] = release_date(catalog.get(slug, {}))
            r["claimed_cutoff"] = OFFICIAL_CUTOFFS.get(slug)
            print(f"  {slug}: reused (tested {r.get('tested_cutoff')}), released {r['released']}")
            rows.append(r)
        else:
            rows.append(probe_one(client, lookup, grader, months, questions, catalog, slug))

    out = ROOT / "out" / "frontier.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"\nWrote {out}")
    for r in rows:
        print(f"  {r['model']:<32} released={r['released']} claim={r['openrouter_cutoff']} "
              f"self={r['self_reported_cutoff']} tested={r['tested_cutoff']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
