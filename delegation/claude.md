# Delegation for Claude Code

This file names the helper for each step of the three skills when you run as Claude Code. Use the Agent tool and set `model` on every call; do not let a helper inherit your model.

## helper per step

| Step | Who | Why |
|---|---|---|
| llm-scan: search for call sites, list files, read functions, collect field names | `haiku` subagent (read-only brief: "list every LLM call site in <repo>; return file:function and the facts in the schema; change nothing") | cheap, fast, reading only |
| llm-scan: fill `routes.json`, decide `user_waits` and `decision_model` | you (main model) | judgement |
| llm-capture: write `adapter.py` | `sonnet` subagent, with the column table from the skill pasted in | code from a clear brief |
| llm-capture: privacy review of the adapter and rows | you | judging risk |
| llm-diagnose: run `calc.py`, join routes, write "where in code" | you | judging, and short |
| Any step that reads large logs or many files | `haiku` or `sonnet` subagent, summary back | keeps your context small |

## rules for helpers

- No model computes numbers. Totals, shares, percentiles, prices and savings come only from `scripts/calc.py`. A helper that returns a number it worked out itself is wrong; rerun calc.
- Give each helper only what it needs: the repo path, the schema, the output path under `work/<repo>/`. Never paste log values or prompt text into a brief.
- Helpers write only under `<pack>/work/<repo>/`. Never the target repo.
- If a helper's output disagrees with the code you can read, trust the code and say so.
