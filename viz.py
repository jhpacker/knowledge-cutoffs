#!/usr/bin/env python3
"""Visualize the recency of OpenRouter's top models' knowledge cutoffs.

Reads out/results.json and renders a grouped horizontal bar chart with THREE bars
per model:
  * Claimed recency       -> OpenRouter's published `knowledge_cutoff`.
  * Self-reported recency  -> the model's own answer when asked directly (#3).
  * Observed recency       -> the empirically *tested* cutoff (source #2).
A lighter extension on the observed bar shows the "partial-knowledge zone" --
months beyond the confirmed cutoff where the model still got *some* (but not all
4) questions right.

Usage:
  python viz.py                       # -> out/recency.png
  python viz.py --in out/results.json --out out/recency.png
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).parent

# Colors -- default scheme distinguishes the three SIGNALS by hue.
C_OBS = "#2563eb"       # observed / tested-cutoff bar (blue)
C_PARTIAL = "#93c5fd"   # partial-knowledge extension (light blue)
C_CLAIM = "#f59e0b"     # claimed cutoff -- OpenRouter (amber)
C_SELF = "#9333ea"      # self-reported cutoff -- model's own claim (purple)

def fmt_release(s: str | None) -> str | None:
    """'YYYY-MM-DD' -> 'May 27, 2026'."""
    if not s:
        return None
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        return None
    return f"{d.strftime('%b')} {d.day}, {d.year}"

# OpenRouter's leaderboard skews toward free / very cheap models, so by default
# we restrict the chart to models from these leading labs. Keys are the provider
# prefixes that appear in OpenRouter slugs (e.g. "openai/gpt-5.5"); values are the
# friendly lab names.
LEADING_LABS = {
    "deepseek": "DeepSeek",
    "anthropic": "Anthropic",
    "qwen": "Alibaba",        # Alibaba's Qwen models
    "alibaba": "Alibaba",
    "moonshotai": "MoonshotAI",
    "google": "Google",
    "openai": "OpenAI",
    "z-ai": "Z-AI",
    "meta-llama": "Meta",
    "meta": "Meta",
}


def provider_of(model: str) -> str:
    return (model or "").split("/", 1)[0].strip().lower()


def ym_to_date(ym: str | None):
    """'YYYY-MM' -> date(YYYY, MM, 1); None/invalid -> None."""
    if not ym:
        return None
    try:
        y, m = ym.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        return None


def most_recent_partial(row: dict):
    """Most recent partial month strictly more recent than the tested cutoff."""
    tested = row.get("tested_cutoff")
    partials = [p for p in row.get("partial_months", [])]
    if not partials:
        return None
    latest = max(partials)
    if tested and latest <= tested:
        return None
    return latest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=str(ROOT / "out" / "results.json"))
    ap.add_argument("--out", dest="out", default=str(ROOT / "out" / "recency.png"))
    ap.add_argument("--order", default="top-weekly")
    ap.add_argument("--labs", default=None,
                    help="comma-separated provider prefixes to include "
                         "(default: the leading-labs allowlist). Use 'all' to disable filtering.")
    ap.add_argument("--models", default=None,
                    help="comma-separated exact model slugs to include "
                         "(overrides --labs; e.g. the frontier model per lab).")
    ap.add_argument("--title", default=None, help="override the chart title")
    args = ap.parse_args()

    rows = json.loads(Path(args.inp).read_text())
    # keep only models we actually probed (have a tested cutoff or some months)
    rows = [r for r in rows if r.get("tested_cutoff") or r.get("partial_months") or r.get("months_detail")]
    if not rows:
        print("No probed models in results.json — run main.py first.")
        return 1

    # --models takes precedence: select exactly those slugs (used for the frontier
    # chart). Otherwise restrict to leading labs (the leaderboard over-weights
    # free/cheap models).
    if args.models:
        want = [s.strip() for s in args.models.split(",") if s.strip()]
        by_slug = {r["model"]: r for r in rows}
        rows = [by_slug[s] for s in want if s in by_slug]
        missing = [s for s in want if s not in by_slug]
        if missing:
            print(f"Not found in results (or not probed): {', '.join(missing)}")
    else:
        if args.labs and args.labs.lower() == "all":
            allow = None
        elif args.labs:
            allow = {p.strip().lower() for p in args.labs.split(",") if p.strip()}
        else:
            allow = set(LEADING_LABS)
        if allow is not None:
            kept = [r for r in rows if provider_of(r["model"]) in allow]
            dropped = [r["model"] for r in rows if provider_of(r["model"]) not in allow]
            if dropped:
                print(f"Filtered out {len(dropped)} non-leading-lab model(s): {', '.join(dropped)}")
            rows = kept
    if not rows:
        print("No models left after filtering.")
        return 1

    # Sort by tested-cutoff recency (oldest at bottom, newest at top).
    def sort_key(r):
        d = ym_to_date(r.get("tested_cutoff"))
        return d or date(1900, 1, 1)

    rows = sorted(rows, key=sort_key)

    def ylabel(r):
        nm = r.get("name") or r["model"]
        rel = fmt_release(r.get("released"))
        return f"{nm}\nReleased {rel}" if rel else nm

    labels = [ylabel(r) for r in rows]
    y = list(range(len(rows)))

    # Baseline = a bit before the earliest date we plot, so bars are readable.
    all_dates = []
    for r in rows:
        for v in (r.get("tested_cutoff"), r.get("openrouter_cutoff"),
                  r.get("claimed_cutoff"), r.get("self_reported_cutoff")):
            d = ym_to_date(v)
            if d:
                all_dates.append(d)
        mp = most_recent_partial(r)
        if mp:
            all_dates.append(ym_to_date(mp))
    if not all_dates:
        print("No dated cutoffs to plot.")
        return 1
    base = min(all_dates)
    base = date(base.year - (1 if base.month <= 3 else 0), ((base.month - 3 - 1) % 12) + 1, 1)
    base_num = mdates.date2num(base)

    fig, ax = plt.subplots(figsize=(11, 1.05 * len(rows) + 2.2))

    bh = 0.24            # height of each of the three bars
    off = bh + 0.02      # vertical offset between adjacent bars

    for yi, r in zip(y, rows):
        # Claimed = provider-official cutoff if present (e.g. Anthropic's docs),
        # else OpenRouter's published field.
        claimed_ym = r.get("claimed_cutoff") or r.get("openrouter_cutoff")
        claimed = ym_to_date(claimed_ym)
        self_rep = ym_to_date(r.get("self_reported_cutoff"))
        tested = ym_to_date(r.get("tested_cutoff"))
        mp_str = most_recent_partial(r)
        mp = ym_to_date(mp_str)

        y_claim = yi + off    # top bar
        y_self = yi           # middle bar
        y_obs = yi - off      # bottom bar

        # --- Claimed bar (provider docs / OpenRouter) ---
        if claimed:
            ax.barh(y_claim, mdates.date2num(claimed) - base_num, left=base_num,
                    height=bh, color=C_CLAIM, zorder=2)
            ax.text(mdates.date2num(claimed) + 6, y_claim, claimed_ym,
                    va="center", ha="left", fontsize=7.5, color="#92400e")

        # --- Self-reported bar (model's own claim) ---
        if self_rep:
            ax.barh(y_self, mdates.date2num(self_rep) - base_num, left=base_num,
                    height=bh, color=C_SELF, zorder=2)
            ax.text(mdates.date2num(self_rep) + 6, y_self, r["self_reported_cutoff"],
                    va="center", ha="left", fontsize=7.5, color="#6b21a8")

        # --- Observed (tested) bar, with partial-knowledge extension behind it ---
        has_partial = bool(mp and (not tested or mp > tested))
        if has_partial:
            ax.barh(y_obs, mdates.date2num(mp) - base_num, left=base_num,
                    height=bh, facecolor=C_PARTIAL, edgecolor=C_OBS,
                    linewidth=0.6, hatch="xxx", zorder=1)
        if tested:
            ax.barh(y_obs, mdates.date2num(tested) - base_num, left=base_num,
                    height=bh, color=C_OBS, zorder=2)

        # Labels sit at their TRUE date so position matches value: the confirmed
        # tested cutoff labels the end of the solid bar; the partial-knowledge
        # extent (if any) labels the end of the hatched zone separately.
        if tested:
            kw = dict(va="center", ha="left", fontsize=7.5, color="#1e3a8a")
            if has_partial:
                # this label lands on top of the hatch -> white bg for legibility
                kw["bbox"] = dict(facecolor="white", edgecolor="none", pad=0.6, alpha=0.85)
            ax.text(mdates.date2num(tested) + 6, y_obs, r["tested_cutoff"], **kw)
        if has_partial:
            ax.text(mdates.date2num(mp) + 6, y_obs, f"{mp_str} partial",
                    va="center", ha="left", fontsize=7, style="italic",
                    color="#3b82f6")

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_ylim(-0.9, len(rows) - 0.1)

    # X axis as dates.
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    ax.set_xlim(base_num, max(mdates.date2num(d) for d in all_dates) + 30)

    ax.set_xlabel("Knowledge cutoff (more recent →)", fontsize=10)
    ax.set_title(args.title or ("OpenRouter top models — claimed vs. self-reported "
                                "vs. observed knowledge-cutoff recency"),
                 fontsize=12.5, fontweight="bold")
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)

    # Legend
    from matplotlib.patches import Patch

    legend = [
        Patch(facecolor=C_CLAIM, label="Claimed recency (provider docs / OpenRouter)"),
        Patch(facecolor=C_SELF, label="Self-reported recency (model's own claim)"),
        Patch(facecolor=C_OBS, label="Observed recency (tested, all-4 confirmed)"),
        Patch(facecolor=C_PARTIAL, edgecolor=C_OBS, hatch="xxx",
              label="Partial-knowledge zone"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=8, framealpha=0.95)

    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
