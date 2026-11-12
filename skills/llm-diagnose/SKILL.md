---
name: llm-diagnose
description: Price a repo's LLM usage and rank what to fix, with every finding tied to a file and function. Use after llm-capture, or when the user says "audit my LLM usage", "why is my LLM bill high", "make my LLM calls faster", "where is my LLM money going", or "diagnose my LLM costs and latency". Runs the bundled calculator; never computes numbers by hand.
---

# llm-diagnose

Needs `work/<repo>/rows.jsonl` (from `llm-capture`) and `work/<repo>/routes.json` (from `llm-scan`).

## 0. Setup

1. Detect which coding agent you are: Claude Code, or Codex (or any other coding agent). Read only `delegation/claude.md` or `delegation/codex.md` in this pack.
2. `<pack>` = the folder that holds `scripts/calc.py`. Write only under `<pack>/work/<repo>/` (the one exception: the short-lived phrases file of the privacy check, in the OS temp folder). Never write into the target repo.

## 1. Ask the provider scope, then run the calculator

Ask the user once, before running calc, in these words: "Stay with your current AI providers, or open to cheaper options from other providers?" Do not ask again. If there is no answer, use `stay`.

- `stay` (default): every action stays inside the providers in the data (caching, trimming, caps, batching, failed-call fixes, a smaller model at the same provider).
- `open`: the report also gets a separate "Other providers" section (HYPOTHESIS, never in the totals).

Pass the answer as `--scope`:

```
python <pack>/scripts/calc.py work/<repo>/rows.jsonl --routes work/<repo>/routes.json --scope stay -o work/<repo>/report.md
```

The headline and the action table are the same under both scopes. `--routes` adds the report's "Scan-only findings" section (usage gaps and routes with no rows, UNMEASURED, no dollars). Other optional flags: `--ttft-budget-ms N` (ask the user for a target if they have one), `--window-days N` (if rows have no timestamps), `--input-excludes-cached` (if the adapter left cache counts out of `input_tokens`), `--label "<text>"`, `--prices <file>`, `--view auto|latency|backoffice|both`. Use `python`, not `python3`. If it exits with an error, fix the input (the message names the column); do not work around it.

Read the top of `report.md` first:

- A **WARNING about unpriced rows** means some spend is missing. Tell the user which models and what share of rows. Do not add a price yourself; ask the user to confirm one from the provider's pricing page, then add it to `scripts/prices.json`.
- **"Spend is a floor"** means some calls have no token usage logged. Tell the user how many calls on how many routes; do not estimate their cost.
- A window under 7 days or an assumed window means monthly figures are weak. Say so.
- When line 1 leads with a MEASURED fact (for example the share of spend that is cache writes) instead of a dollar saving, no output-neutral saving was computable; say that, and copy the fact as the report words it.
- A **Logged cost check** line compares the app's own logged cost with the priced total; if it says the logged cost looks cumulative, the logged number is not a per-call cost. Say so and rely on the priced figure.

## 2. Where in code

Never compute numbers by hand. Every number you state is copied from `report.md`.

Write `work/<repo>/diagnosis.md`. Start it with one line, "Provider scope: stay" or "Provider scope: open (the user's answer, or the default)". Then a short section "Where in code". Take the top findings from the report's action table (up to five), the report's "Measured findings with no savings dollar" section when it has rows (copied as worded, no savings dollar), and the report's "Cache in use (MEASURED)" section when it has rows: list its largest route and model with the cache-read, 5-minute-write and 1-hour-write dollars, the write-versus-read ratio and the writes-after-the-first-call count, copied from the report, with no savings dollar. Also list, copied as worded and joined to routes.json the same way, with no dollar added to any total: the report's "Unused tool schemas" rows (MEASURED dollars, action HYPOTHESIS; routes.json `tools` says where the definitions are built), its "Spirals" rows (MEASURED; "not enough tasks" copied as is), and, only when the scope is open, the "Other providers" section (HYPOTHESIS: candidate, list-price figure, switching cost and eval exactly as written; say the figures are outside the headline). Any row the report marks "low evidence" stays marked in `diagnosis.md`; say it is a lead, not a result.

For each finding:

- the finding, as the report words it, with its dollar range and label (MEASURED / MECHANICAL / HYPOTHESIS) copied verbatim;
- the route id(s) from the report, joined to `routes.json`: `file:function`, plus the facts from routes.json that explain it (for example `streaming: false`, `cache_markers: implicit`, `stateless`, `max_tokens: null`, `retries`, `user_waits`);
- the one change to try, in a sentence, and how the report says to check it.

Add one line for routes in routes.json with no rows in the report (the report's "Scan-only findings" lists them), and one for report routes not in routes.json. Copy the `usage_gaps` as UNMEASURED, with no dollars. Add the speed line (TTFT p50 and p95 per user-facing route, or the report's "n < 200" statement) copied from the report.

If a calc finding contradicts what the code or the rows show, keep calc's number and say so in `diagnosis.md` under "Findings that do not fit", with the evidence (`file:line` or column counts). Do not change the number or the report.

Leave `report.md` as calc wrote it so `calc.py` reproduces it exactly.

## 3. Privacy check

1. Run `python <pack>/scripts/check_rows.py work/<repo>/rows.jsonl`.
2. Write a phrases file in the OS temp folder, never under `work/`: pick up to ten distinctive phrases (5-8 words each) from the app's own logs or prompts, plus three or four raw task or session ids, one per line. Do not print them or paste them into chat.
3. Run `python <pack>/scripts/privacy_check.py work/<repo> --phrases-file <that file>`. It searches every file under `work/<repo>/` (report.md, diagnosis.md, rows.jsonl, adapter.py, routes.json) and prints which phrase line hit which file, never the phrase or its context. Exit 0 means no hits.
4. Delete the phrases file.

If anything leaks, delete the leaking file, fix the adapter or the note, and rerun. The report shows 12-character hashes for task and session ids; a raw id in any file is a leak.

## 4. Finish

Tell the user in under ten lines: the headline from `report.md` line 1, the top three findings with their `file:function`, any unpriced warning, and that every number can be reproduced by rerunning the command above. Ask before changing any code in their repo.
