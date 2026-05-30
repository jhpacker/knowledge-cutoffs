"""Source #1: publicly claimed knowledge cutoffs.

Primary source: the HaoooWang/llm-knowledge-cutoff-dates repo, whose data lives
as HTML tables inside its README.md. We parse those tables into a lookup of
(provider, model name) -> cutoff (YYYY.MM), and fuzzy-match against OpenRouter
model names.

Anthropic's table distinguishes "Training Data Cut-off" from "Reliable Knowledge
Cut-off"; per the task we take the *Training Data* cut-off.

As a secondary fallback we use OpenRouter's own published `knowledge_cutoff`
field (clearly labelled as such in the output).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

README_URL = (
    "https://raw.githubusercontent.com/HaoooWang/"
    "llm-knowledge-cutoff-dates/main/README.md"
)


@dataclass
class PublicCutoff:
    cutoff: str | None  # "YYYY-MM" normalized, or None
    source: str  # "repo" | "openrouter" | "none"
    raw_model: str | None = None


def _normalize_ym(text: str) -> str | None:
    """Accept '2024.04', '2024-04', '2024/04', 'April 2024', '2023' -> 'YYYY-MM'."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.search(r"([A-Za-z]{3,9})[ ,]+(20\d{2})", t)
    if m and m.group(1)[:3].lower() in months:
        return f"{m.group(2)}-{months[m.group(1)[:3].lower()]:02d}"
    m = re.search(r"\b(20\d{2})\b", t)
    if m:
        return f"{m.group(1)}-12"  # year-only -> treat as end of year
    return None


def _norm_name(s: str) -> str:
    """Loose key for fuzzy matching: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _strip_md(cell: str) -> str:
    """Strip markdown link syntax, keeping link text: [txt](url) -> txt."""
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return cell.strip()


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line)) and "-" in line


def fetch_repo_table(timeout: int = 30, text: str | None = None) -> list[dict]:
    """Parse the repo README's Markdown pipe tables.

    Returns list of {provider, model, cutoff_ym, raw_cutoff}. When an Anthropic-
    style table has both "Training Data Cut-off" and "Reliable Knowledge Cut-off",
    we take the Training Data column per the task.
    """
    if text is None:
        r = requests.get(README_URL, timeout=timeout)
        r.raise_for_status()
        text = r.text

    lines = text.splitlines()
    rows: list[dict] = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        if "|" in line and _is_separator(lines[i + 1]):
            headers = [h.lower() for h in _split_row(line)]
            model_i = next((j for j, h in enumerate(headers) if "model" in h), None)
            company_i = next(
                (j for j, h in enumerate(headers) if "company" in h or "provider" in h),
                None,
            )
            train_i = next(
                (j for j, h in enumerate(headers) if "cut" in h and "train" in h), None
            )
            cut_i = next(
                (
                    j
                    for j, h in enumerate(headers)
                    if "cut" in h and "reliable" not in h
                ),
                None,
            )
            cutoff_i = train_i if train_i is not None else cut_i
            i += 2  # skip header + separator
            if model_i is None or cutoff_i is None:
                continue
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                cells = _split_row(lines[i])
                i += 1
                if len(cells) <= max(model_i, cutoff_i):
                    continue
                model = _strip_md(cells[model_i])
                raw_cut = _strip_md(cells[cutoff_i])
                provider = (
                    _strip_md(cells[company_i])
                    if company_i is not None and len(cells) > company_i
                    else ""
                )
                if not model:
                    continue
                rows.append(
                    {
                        "provider": provider,
                        "model": model,
                        "cutoff_ym": _normalize_ym(raw_cut),
                        "raw_cutoff": raw_cut,
                    }
                )
        else:
            i += 1
    return rows


class PublicCutoffLookup:
    def __init__(self, repo_rows: list[dict]):
        self.rows = [r for r in repo_rows if r.get("cutoff_ym")]
        # index by normalized model name
        self.by_name = {}
        for r in self.rows:
            self.by_name.setdefault(_norm_name(r["model"]), r)

    def match(self, or_model: dict) -> PublicCutoff:
        """Fuzzy-match an OpenRouter model dict against the repo table."""
        name = or_model.get("name") or or_model.get("short_name") or ""
        slug = or_model.get("slug") or or_model.get("id") or ""
        # strip provider prefix from name like "OpenAI: GPT-4o"
        cand_strs = [name]
        if ":" in name:
            cand_strs.append(name.split(":", 1)[1])
        cand_strs.append(slug.split("/")[-1] if "/" in slug else slug)
        cand_keys = {_norm_name(c) for c in cand_strs if c}

        # exact normalized match first
        for k in cand_keys:
            if k in self.by_name:
                row = self.by_name[k]
                return PublicCutoff(row["cutoff_ym"], "repo", row["model"])
        # containment match (repo name contained in candidate or vice-versa)
        best = None
        for key, row in self.by_name.items():
            for ck in cand_keys:
                if len(key) >= 6 and (key in ck or ck in key):
                    # prefer longer overlap
                    score = min(len(key), len(ck))
                    if best is None or score > best[0]:
                        best = (score, row)
        if best:
            row = best[1]
            return PublicCutoff(row["cutoff_ym"], "repo", row["model"])
        return PublicCutoff(None, "none")


def openrouter_published_cutoff(or_model: dict) -> str | None:
    """Secondary source: OpenRouter's own knowledge_cutoff field -> 'YYYY-MM'."""
    kc = or_model.get("knowledge_cutoff")
    if not kc:
        return None
    return _normalize_ym(kc) or _normalize_ym(str(kc)[:7])
