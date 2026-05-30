# CLAUDE.md

Context for Claude (and humans) picking this project back up. Read this first.

## What this project does

Discovers and compares the **knowledge-cutoff date** of the most popular models
on OpenRouter's leaderboard, from three signals, and renders a chart:

1. **Repo cutoff (#1, claimed):** the community-collected
   [HaoooWang/llm-knowledge-cutoff-dates](https://github.com/HaoooWang/llm-knowledge-cutoff-dates)
   repo. For Anthropic we use the **Training Data cut-off**, not the Reliable
   Knowledge cut-off. Parsed from the README's Markdown pipe tables.
2. **OpenRouter cutoff (claimed):** the `knowledge_cutoff` field on
   `/api/v1/models`. Shown as its own column to see where it matches/differs.
3. **Tested cutoff (#2, observed):** an empirical month-by-month "walk-back"
   probe over real news events (see method below).

Output: `out/results.{md,json,csv}` (table) and `out/recency.png` (chart).

## The tested-cutoff method (`src/probe.py`)

- Each month in `questions.json` has **4 questions** about hard-to-guess news
  events (a sports winner, a death, a specific disaster name/place).
- Walk months from most-recent backward. **All 4** must be answered correctly
  for a month to **pass**. Some-but-not-all correct = **partial**; none = fail.
- Require **two consecutive passed months** to confirm (guards against a lucky
  guess). The tested cutoff = the most recent of those two months.
- Any non-pass (partial or fail) resets the streak. Partial months are surfaced
  separately (and drawn as a hatched "partial-knowledge zone" in the chart).
- Grading is **keyword-only** by default: correct iff any `accept` substring
  appears in the reply (case-insensitive) and the reply isn't a refusal. Pass
  `--judge <model>` to add an LLM equivalence check.

### Question design rules (important)

Answers must be SHORT, DISTINCTIVE tokens **and** UNGUESSABLE outcomes that
can't be inferred from static/pre-event knowledge, the question wording, or
base-rate likelihood. Avoid: binary win/lose framing, base-rate favorites
(e.g. "Norway tops Winter Olympics"), only-one-plausible-answer/static-ID
questions, and portmanteau leaks. The gold standard = broad category + an
underivable specific name (e.g. a specific death or upset winner).

The user curates `questions.json` by hand and culls weak questions; **do not
revert their edits.** When asked to refill, only add questions in the
**sports / deaths / disasters** vein, never reuse a question they rejected, and
keep all 35 months at exactly **4 questions**. Their manual edits sometimes
leave trailing commas (invalid JSON) — re-validate after they touch it.

## Layout

- `main.py` — orchestration + Markdown/CSV/JSON table rendering.
- `viz.py` — grouped horizontal bar chart: **claimed (OpenRouter)** vs.
  **observed (tested)** recency, with a hatched partial-knowledge zone. Filters
  to leading labs by default (see below).
- `questions.json` — `{ "_meta": ..., "months": { "YYYY-MM": { "questions":[4] }}}`.
- `src/` — the Python package (importable as `src.*`). Internal modules use
  relative imports; only `main.py` imports the package by name.
  - `openrouter.py` — API client: `list_models()`, `top_models(order=...)`
    (frontend leaderboard endpoint), `chat(...)`.
  - `public_cutoffs.py` — source #1 repo Markdown parser + fuzzy name matching;
    `openrouter_published_cutoff()` reads the `/models` field.
  - `grader.py` — keyword + optional LLM-judge grading.
  - `probe.py` — the walk-back algorithm.

Note: the package dir is `src/` (renamed from `kc/`). `src` is the import name,
which is slightly unidiomatic for a Python package but matches the requested
`src/` layout; `python main.py` from the repo root works because the root is on
`sys.path`.

## Running

```bash
pip install -r requirements.txt
cp .env.example .env            # add OPENROUTER_API_KEY (the real .env is gitignored)

python main.py --dry-run        # leaderboard + claimed cutoffs, no API spend
python main.py --top 20         # full run (keyword grading by default)
python main.py --models "openai/gpt-4o-mini,google/gemini-2.5-flash,openai/gpt-5.5" \
               --judge none --verbose   # the standard 3-model spot-check

python viz.py                   # -> out/recency.png (leading-labs filter on)
python viz.py --labs all        # include every probed model
```

## Leading-labs filter (`viz.py`)

OpenRouter's leaderboard skews toward free / very cheap models, so the chart
restricts to these labs by default (matched on the slug provider prefix):
**DeepSeek, Anthropic, Alibaba (`qwen`), MoonshotAI, Google, OpenAI, Z-AI,
Meta (`meta-llama`)**. Override with `--labs <prefixes>` or `--labs all`.

## State / history

- Methodology evolved from "2 selected questions/month, both correct" to
  "**all 4** questions/month, all correct" with a **partial** state. `selected`/
  `recommend` fields were removed from `questions.json` (the probe now uses every
  question). The per-month array key is `questions` (renamed from `candidates`).
- Spot-check findings (3 models, all-4 method): under the stricter rule observed
  cutoffs drop well below claimed (e.g. `gpt-5.5` claimed 2025-12 → observed
  ~2024-10; `gpt-4o-mini` can't even confirm its claimed 2023-10 — only
  scattered partials). This is the intended "demonstrates complete knowledge"
  signal, not a bug.
- `2026-01 … 2026-04` questions are recent and were sourced via web search
  (Catherine O'Hara, Johannes Klaebo's 6 golds, Garrett Anderson, Rory McIlroy's
  repeat Masters, etc.); re-verify if results look off.
- Public repo: https://github.com/jhpacker/knowledge-cutoffs
- The full **top-20** run has been designed but only **spot-checks** have been
  run so far — get explicit go-ahead before launching the full run (it spends
  real API budget).

## Gotchas

- `.env` holds a real key — it's gitignored; never commit it. `out/*.log` and
  `.claude/` are gitignored too.
- Background runs need `python3 -u` + file redirect (stdout buffering otherwise
  shows stale/empty logs); wait on the PID, not on grepping the buffered log.
- The HaoooWang data is **Markdown tables**, not HTML — don't reach for an HTML
  parser.
