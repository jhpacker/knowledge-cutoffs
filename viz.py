#!/usr/bin/env python3
"""Visualize the recency of OpenRouter's top models' knowledge cutoffs.

Reads out/results.json and renders a grouped horizontal bar chart with TWO bars
per model:
  * Claimed recency  -> OpenRouter's published `knowledge_cutoff`.
  * Observed recency -> the empirically *tested* cutoff (source #2).
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

# Colors
C_OBS = "#2563eb"       # observed / tested-cutoff bar (blue)
C_PARTIAL = "#93c5fd"   # partial-knowledge extension (light blue)
C_CLAIM = "#f59e0b"     # claimed cutoff -- OpenRouter (amber)


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
    args = ap.parse_args()

    rows = json.loads(Path(args.inp).read_text())
    # keep only models we actually probed (have a tested cutoff or some months)
    rows = [r for r in rows if r.get("tested_cutoff") or r.get("partial_months") or r.get("months_detail")]
    if not rows:
        print("No probed models in results.json — run main.py first.")
        return 1

    # Sort by tested-cutoff recency (oldest at bottom, newest at top).
    def sort_key(r):
        d = ym_to_date(r.get("tested_cutoff"))
        return d or date(1900, 1, 1)

    rows = sorted(rows, key=sort_key)

    labels = [r.get("name") or r["model"] for r in rows]
    y = list(range(len(rows)))

    # Baseline = a bit before the earliest date we plot, so bars are readable.
    all_dates = []
    for r in rows:
        for v in (r.get("tested_cutoff"), r.get("openrouter_cutoff")):
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

    fig, ax = plt.subplots(figsize=(11, 0.85 * len(rows) + 2.2))

    bh = 0.34  # height of each of the two bars

    for yi, r in zip(y, rows):
        claimed = ym_to_date(r.get("openrouter_cutoff"))
        tested = ym_to_date(r.get("tested_cutoff"))
        mp = ym_to_date(most_recent_partial(r))

        y_claim = yi + bh / 2 + 0.02   # upper bar
        y_obs = yi - bh / 2 - 0.02     # lower bar

        # --- Claimed (OpenRouter) bar ---
        if claimed:
            ax.barh(y_claim, mdates.date2num(claimed) - base_num, left=base_num,
                    height=bh, color=C_CLAIM, zorder=2)
            ax.text(mdates.date2num(claimed) + 6, y_claim, r["openrouter_cutoff"],
                    va="center", ha="left", fontsize=7.5, color="#92400e")

        # --- Observed (tested) bar, with partial-knowledge extension behind it ---
        if mp and tested and mp > tested:
            ax.barh(y_obs, mdates.date2num(mp) - base_num, left=base_num,
                    height=bh, facecolor=C_PARTIAL, edgecolor=C_OBS,
                    linewidth=0.6, hatch="xxx", zorder=1)
        if tested:
            ax.barh(y_obs, mdates.date2num(tested) - base_num, left=base_num,
                    height=bh, color=C_OBS, zorder=2)
            ax.text(mdates.date2num(tested) + 6, y_obs, r["tested_cutoff"],
                    va="center", ha="left", fontsize=7.5, color="#1e3a8a")
        elif mp:
            ax.text(mdates.date2num(mp) + 6, y_obs, f"~{r['tested_cutoff'] or 'none'}",
                    va="center", ha="left", fontsize=7.5, color="#1e3a8a")

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_ylim(-0.8, len(rows) - 0.2)

    # X axis as dates.
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    ax.set_xlim(base_num, max(mdates.date2num(d) for d in all_dates) + 30)

    ax.set_xlabel("Knowledge cutoff (more recent →)", fontsize=10)
    ax.set_title("OpenRouter top models — claimed vs. observed knowledge-cutoff recency",
                 fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)

    # Legend
    from matplotlib.patches import Patch

    legend = [
        Patch(facecolor=C_CLAIM, label="Claimed recency (OpenRouter)"),
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
