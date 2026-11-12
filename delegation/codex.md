# Delegation for Codex / ChatGPT

This file names who does each step of the three skills when you run as Codex or a ChatGPT coding agent. Items marked [unsure] depend on your setup; use the closest thing you have.

## helper per step

| Step | Who | Why |
|---|---|---|
| llm-scan: search for call sites, list files, read functions, collect field names | a smaller, faster model if your setup can run one for read-only work [unsure: a Codex session may use one model throughout; then do it yourself with `rg`/grep] | cheap, reading only |
| llm-scan: fill `routes.json`, decide `user_waits` and `decision_model` | your main model | judgement |
| llm-capture: write `adapter.py` | your main model, with the column table from the skill | code from a clear brief |
| llm-capture: privacy review of the adapter and rows | your main model, plus `scripts/check_rows.py` | judging risk |
| llm-diagnose: run `calc.py`, join routes, write "where in code" | your main model | judging, and short |
| Reading very large logs | a shell command that prints only field names and counts, not values | keeps text out of your context |

## rules

- No model computes numbers. Totals, shares, percentiles, prices and savings come only from `scripts/calc.py`. If you worked a number out yourself, discard it and rerun calc.
- Run commands with `python`, from the pack folder, in the user's shell [unsure: on Windows use PowerShell syntax; no `&&`].
- Write only under `<pack>/work/<repo>/`. Never the target repo.
- If you can start separate agents (cloud tasks, subagents) [unsure], give each only the repo path, the schema and the output path; never paste log values or prompt text.
