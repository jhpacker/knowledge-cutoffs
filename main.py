#!/usr/bin/env python3
"""Discover knowledge-cutoff dates for OpenRouter's most popular models.

Outputs a table of: model | public cutoff (source #1) | tested cutoff (source #2).

  Source #1  publicly claimed cutoff  -> HaoooWang/llm-knowledge-cutoff-dates
             repo (Anthropic: Training Data cut-off), with OpenRouter's own
             published cutoff as a labelled fallback.
  Source #2  empirically tested cutoff -> month-by-month walk-back probe.

Examples:
  python main.py --dry-run            # leaderboard + public cutoffs, no probing
  python main.py --top 20             # full run, default judge
  python main.py --top 5 --judge none # keyword-only grading, cheaper
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.grader import Grader
from src.openrouter import OpenRouter
from src.probe import probe_model, questions_for_month
from src.public_cutoffs import (
    PublicCutoffLookup,
    fetch_repo_table,
    openrouter_published_cutoff,
)

ROOT = Path(__file__).parent
OUT = ROOT / "out"
DEFAULT_JUDGE = "none"  # keyword-only grading (answers are short + distinctive)


def load_questions() -> dict:
    data = json.loads((ROOT / "questions.json").read_text())
    return data["months"]


def usable_months(questions: dict) -> list[str]:
    """Months (most-recent-first) that have at least one question."""
    months = sorted(questions.keys(), reverse=True)
    return [m for m in months if questions_for_month(questions[m])]


def fmt(v) -> str:
    return v if v else "—"


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=20, help="number of leaderboard models (default 20)")
    ap.add_argument("--order", default="top-weekly", help="leaderboard order (default top-weekly)")
    ap.add_argument("--judge", default=DEFAULT_JUDGE, help="judge model id, or 'none' for keyword-only")
    ap.add_argument("--dry-run", action="store_true", help="no probing; show leaderboard + public cutoffs only")
    ap.add_argument("--verbose", action="store_true", help="print per-month probe progress")
    ap.add_argument("--limit-models", type=int, default=None, help="probe only the first N models (debug)")
    ap.add_argument("--models", default=None, help="comma-separated slugs to probe instead of the leaderboard")
    args = ap.parse_args()

    try:
        client = OpenRouter()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Fetching top {args.top} models ({args.order}) ...")
    all_models = client.top_models(order=args.order)
    if args.models:
        wanted = [s.strip() for s in args.models.split(",") if s.strip()]
        by_slug = {m.get("slug") or m.get("id"): m for m in all_models}
        leaderboard = [
            by_slug.get(w, {"slug": w, "name": w}) for w in wanted
        ]
    else:
        leaderboard = all_models[: args.top]

    print("Fetching public cutoff data (HaoooWang repo) ...")
    try:
        repo_rows = fetch_repo_table()
        lookup = PublicCutoffLookup(repo_rows)
        print(f"  parsed {len(lookup.rows)} dated rows from repo")
    except Exception as e:
        print(f"  WARNING: could not load repo data ({e}); using OpenRouter cutoffs only")
        lookup = PublicCutoffLookup([])

    questions = load_questions()
    months = usable_months(questions)
    print(f"Probe range: {months[-1]} .. {months[0]} ({len(months)} months, most-recent-first)\n")

    judge_model = None if args.judge.lower() == "none" else args.judge
    grader = Grader(client, judge_model)

    rows = []
    probe_targets = leaderboard if args.limit_models is None else leaderboard[: args.limit_models]

    for i, m in enumerate(leaderboard, 1):
        slug = m.get("slug") or m.get("id")
        name = m.get("name") or slug

        repo_cutoff = lookup.match(m).cutoff            # source #1: HaoooWang repo
        or_cutoff = openrouter_published_cutoff(m)       # OpenRouter /models field

        tested_cutoff = None
        note = ""
        months_detail: list[dict] = []
        if not args.dry_run and (args.limit_models is None or i <= args.limit_models):
            print(f"[{i}/{len(leaderboard)}] probing {slug} ...")
            res = probe_model(client, grader, slug, months, questions, verbose=args.verbose)
            tested_cutoff = res.tested_cutoff
            note = res.note
            months_detail = [
                {
                    "month": mr.month,
                    "status": mr.status,
                    "n_correct": mr.n_correct,
                    "n_total": mr.n_total,
                }
                for mr in res.months_tested
            ]

        repo_vs_or = ""
        if repo_cutoff and or_cutoff:
            repo_vs_or = "match" if repo_cutoff == or_cutoff else "differ"

        partial_months = [d["month"] for d in months_detail if d["status"] == "partial"]

        rows.append(
            {
                "rank": i,
                "model": slug,
                "name": name,
                "repo_cutoff": repo_cutoff,        # source #1
                "openrouter_cutoff": or_cutoff,    # OpenRouter /models knowledge_cutoff
                "repo_vs_openrouter": repo_vs_or,
                "tested_cutoff": tested_cutoff,    # source #2
                "partial_months": partial_months,
                "months_detail": months_detail,
                "note": note,
            }
        )

    # ---- render -------------------------------------------------------
    OUT.mkdir(exist_ok=True)
    md = render_markdown(rows, args)
    (OUT / "results.md").write_text(md)
    (OUT / "results.json").write_text(json.dumps(rows, indent=2))
    csv_cols = [
        "rank", "model", "name", "repo_cutoff", "openrouter_cutoff",
        "repo_vs_openrouter", "tested_cutoff", "partial_months", "note",
    ]
    with (OUT / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = dict(r)
            row["partial_months"] = ";".join(r.get("partial_months", []))
            w.writerow(row)

    print("\n" + md)
    print(f"\nWrote out/results.md, out/results.json, out/results.csv")
    return 0


def render_markdown(rows: list[dict], args) -> str:
    lines = [
        "# OpenRouter Top Models — Knowledge Cutoff Comparison",
        "",
        f"Leaderboard order: `{args.order}` · top {args.top}"
        + ("" if args.dry_run else f" · judge: `{args.judge}`"),
        "",
        "| # | Model | Repo cutoff (#1) | OpenRouter cutoff | Tested cutoff (#2) | Partial months | Notes |",
        "|---|-------|------------------|-------------------|--------------------|----------------|-------|",
    ]
    for r in rows:
        tested = "(dry-run)" if args.dry_run else fmt(r["tested_cutoff"])
        partials = r.get("partial_months", [])
        partial_cell = ", ".join(partials) if partials else "—"
        note = " · ".join(x for x in [r.get("repo_vs_openrouter"), r["note"]] if x)
        lines.append(
            f"| {r['rank']} | `{r['model']}` | {fmt(r['repo_cutoff'])} | "
            f"{fmt(r['openrouter_cutoff'])} | {tested} | {partial_cell} | {note} |"
        )
    lines += [
        "",
        "_**Repo cutoff (#1):** HaoooWang/llm-knowledge-cutoff-dates "
        "(Anthropic = Training Data cut-off)._",
        "_**OpenRouter cutoff:** the `knowledge_cutoff` field from OpenRouter's "
        "`/api/v1/models`. Notes flag whether it `match`es or `differ`s from the repo._",
        "_**Tested cutoff (#2):** month-by-month walk-back probe; a month passes only "
        "if **all 4** questions are correct, and the cutoff is the most recent of two "
        "consecutive passed months._",
        "_**Partial months:** months where the model got some (but not all 4) "
        "questions right._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
