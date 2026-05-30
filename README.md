# Knowledge-Cutoff Discovery for OpenRouter's Top Models

Discovers the knowledge-cutoff date of the most popular models on OpenRouter's
daily leaderboard, from **two** sources, and prints a comparison table:

| Column | What | How |
|--------|------|-----|
| **Repo cutoff (#1)** | The cutoff the provider *claims*, community-collected | The [HaoooWang/llm-knowledge-cutoff-dates](https://github.com/HaoooWang/llm-knowledge-cutoff-dates) repo. For Anthropic, the **Training Data cut-off** is used (not the Reliable Knowledge cut-off). |
| **OpenRouter cutoff** | The cutoff OpenRouter publishes | The `knowledge_cutoff` field on `/api/v1/models`. Shown as its own column so you can see where it `match`es or `differ`s from the repo. |
| **Tested cutoff (#2)** | The cutoff the model actually *demonstrates* | A month-by-month "walk-back" probe over real news events. |

## The tested-cutoff method

1. Each month has **4 questions** about major, hard-to-guess news events
   (`questions.json`). All 4 are asked.
2. Walk months from the most recent backward in time. A month is **passed** only
   if the model answers **all 4** questions correctly. If it gets some (but not
   all 4) right, the month is **partial**; none right is a **fail**.
3. Require **two consecutive passed months** to confirm (guards against a lucky
   single guess). The tested cutoff is the **most recent** of those two months.
4. Any non-pass month (partial or fail) resets the streak. Partial months are
   surfaced separately in the output so you can see where a model has fading,
   incomplete knowledge just past its confirmed cutoff.

Answers are graded keyword-only by default (answers are short and distinctive);
pass `--judge <model>` to add an LLM equivalence check. Refusals count as wrong.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # then add your OpenRouter API key
```

## Run

```bash
python main.py --dry-run          # leaderboard + public cutoffs, no API spend
python main.py --top 20           # full run (default judge: google/gemini-2.5-flash)
python main.py --top 5 --judge none --verbose   # cheap keyword-only smoke run
```

Outputs land in `out/` as `results.md`, `results.json`, `results.csv`.

## Questions

Each month in `questions.json` has **4 questions**, and the probe asks all of
them. A month only counts as passed when the model gets every one right, so the
questions should be unguessable (specific named winners/deaths/results, not
base-rate favorites or binary outcomes).

## Visualizing

After a run, render a horizontal bar chart of cutoff recency:

```bash
python viz.py            # reads out/results.json -> out/recency.png
```

Each bar's right edge is the tested cutoff; a lighter extension marks the
"partial-knowledge zone"; diamond/triangle markers overlay the repo and
OpenRouter claimed cutoffs.

## Layout

- `main.py` — orchestration + table rendering
- `viz.py` — horizontal bar chart of cutoff recency (claimed vs. observed)
- `questions.json` — probe questions (4 per month)
- `src/openrouter.py` — API client (chat + leaderboard)
- `src/public_cutoffs.py` — source #1 (repo parser + fuzzy matching)
- `src/grader.py` — LLM judge + keyword grading
- `src/probe.py` — source #2 walk-back algorithm
