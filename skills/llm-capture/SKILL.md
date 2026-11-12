---
name: llm-capture
description: Turn an app's existing usage logs into rows.jsonl, the numeric-only input the LLM cost and latency calculator needs, or give the user a tiny logging shim if no logs exist. Use after llm-scan, or when the user says "get my LLM usage data", "prepare my logs for the audit", "I have no LLM logging", or "export token usage". Never copies prompt, answer or user text.
---

# llm-capture

This skill turns an app's usage logs into `work/<repo>/rows.jsonl`, or gives the user a logging shim when no logs exist. It needs `work/<repo>/routes.json` from `llm-scan`; if it is missing, run `llm-scan` first.

## 0. set up

1. Detect which coding agent you are: Claude Code, or Codex (or any other coding agent). Read only `delegation/claude.md` or `delegation/codex.md` in this pack for which model does which step.
2. Set `<pack>` to the folder that holds `scripts/calc.py`. Write only under `<pack>/work/<repo>/`. Never write into, or run anything that writes into, the target repo.

## 1. privacy rules (hard)

- `rows.jsonl` holds numeric and categorical columns only. Never prompt text, completion text, transcript, tool output, file contents, names, emails or any user text.
- Build rows from an allowlist: copy named fields only. Never pass through unknown fields or whole log records.
- Hash ids (`task_id`, `session_id`, `prefix_hash`) in the adapter: first 12 hex chars of sha256 of the raw id. Never write a raw id. A content prefix hash is a hash of the stable prompt prefix, computed in the adapter and never stored as text. If the logs hold no prompt text, see `prefix_hash` below.
- Nothing leaves this laptop. No uploads, no network calls.

## 2. if logs exist (see `usage_logs` in routes.json)

Write a small stdlib-only script `work/<repo>/adapter.py` that reads the app's logs and writes `work/<repo>/rows.jsonl`, one JSON object per model call (including decision-model calls), using exactly these columns. Put a header comment in `adapter.py` that states every choice the rules below leave to you (where `model` came from, how ids are hashed, the input convention, the prefix-hash kind).

| column | type | note |
|---|---|---|
| `model` | string | required; as logged (see "model" below) |
| `input_tokens` | number | required; INCLUDES cached reads and cache writes (below) |
| `output_tokens` | number | required; `0` only for a model whose provider bills input only (see "output tokens" below) |
| `route` | string | route id from routes.json (`path:function` or `path:Class.method`); map from whatever the log has |
| `timestamp` | epoch seconds or ISO string | |
| `cached_input_tokens` | number | cache reads |
| `cache_write_tokens` | number | 5-minute cache writes only |
| `cache_write_1h_tokens` | number | 1-hour cache writes (aliases: `ephemeral_1h_input_tokens`) |
| `ttft_ms` | number | time to first token, in MILLISECONDS |
| `latency_ms` | number | whole call, in MILLISECONDS |
| `success` | true / false | |
| `streamed` | true / false | |
| `task_id`, `session_id` | string | hashed; omit `session_id` on stateless routes |
| `prefix_hash` | string | hashed; same value for calls that share a stable prefix |
| `prefix_hash_kind` | `content` / `structural` | set to `structural` when the hash is not of prompt text (below) |
| `prefix_tokens` | number | size of that prefix |
| `usage_missing` | true | the call happened but the log has no token usage (below) |
| `stateless` | true | the route is stateless in routes.json (each call stands alone) |
| `logged_cost_usd` | number | optional; the cost the app logged for this call, as logged |
| `tools_defined` | number | optional; how many tool or function definitions the request carried |
| `tool_schema_tokens` | number | optional; tokens the tool definitions take in the request, when the log holds that size |
| `tool_calls` | number | optional; how many tool calls the response made (`0` is meaningful: the schema was sent and no tool was called) |

Convert times to ms (seconds x 1000) and write tokens as counts (not thousands). If the log reports input, cache read and cache creation as separate numbers (the usual provider usage shape), pick one of these and say which:

- add them into `input_tokens` in the adapter;
- leave them separate and tell the user to run calc with `--input-excludes-cached`.

If the log gives a total cache-creation number and a 1-hour part, put the 1-hour part in `cache_write_1h_tokens` and the rest in `cache_write_tokens`.

Never invent a value. These are the allowed sources:

- For `model`, take it from the log record. If the record has none, take it from a joined event of the same call (same id, no text copied) or from a constant in the code that sets it (`model_source` in routes.json). Say which in the adapter header comment. If none exists, the row has no model: skip it and count it.
- For `output_tokens` on a model whose provider bills input only (decision models), write `0` and say so in the adapter header comment. For any other model, a missing output count makes the row `usage_missing`: do not fill it in, and do not write `0`.
- If a call is logged but has no token usage (warm-up and keepalive calls, calls whose response was not saved), do not drop it. Emit a row with `usage_missing: true`, plus `route`, `model` if known, `timestamp` and `latency_ms` if present, and no token columns. calc counts these per route, leaves them out of spend and states that spend is a floor. Log lines for model calls that failed or were discarded, with no usage, are rows too: emit them as `usage_missing: true` with `success: false`.
- For routes with `stateless: true` in routes.json, emit `stateless: true` and omit `session_id`.
- For `prefix_hash`, hash the stable prefix text in the adapter when the logs hold it. If the logs hold no prompt text, emit a structural hash instead (first 12 hex chars of sha256 of route + model + the process or worker generation id), set `prefix_hash_kind` to `structural`, and say so in the adapter header comment. calc then states in the report that the hash is structural and the caching figure assumes the prefix is stable. If there is no process or worker id either, omit `prefix_hash`.
- Emit `tools_defined`, `tool_schema_tokens` and `tool_calls` only when the logs carry them (the scan's note on tool fields says where). They are counts: never a tool name, a tool argument or a tool result. Do not estimate the schema size from the code; if only the count of tools is logged, emit `tools_defined` and leave out `tool_schema_tokens`. Emit `tool_calls: 0` only when the log shows the response had no tool call; if the log does not say, omit the column. Say in the adapter header comment where each came from.
- Copy `logged_cost_usd` as logged. It may be a running total per process or session; calc prints a reconciliation line against the priced total and warns about that.

Non-LLM model calls (speech-to-text and the like) are out of scope. They are listed in routes.json with `kind: non_llm`; emit no rows for them.

Skip a column if the log does not have it; do not invent values. Skip and count rows with no model, and rows with token fields that are not numbers and no `usage_missing` reason.

Then verify:

1. Run the adapter, then `python <pack>/scripts/check_rows.py work/<repo>/rows.jsonl`. It fails on any column outside the schema or any long or multi-word text value. Fix the adapter until it passes.
2. Print the row count, the date range, how many rows each route has, and how many rows are `usage_missing` per route. Tell the user about routes with no rows.

## 3. if no logs exist

1. Do not edit the repo.
2. Give the user, in chat, a minimal logging shim for their language to paste themselves if they choose. After each model call it appends one JSON line to a local file with only the columns above (model, token counts, cache counts, `ttft_ms`, `latency_ms`, `route`, `success`, `streamed`, hashed ids, timestamp), never text.
3. Make the shim log a `usage_missing` row when a call returns no usage, rather than skipping the call.
4. Put the shim in each route from `routes.json` that matters most.
5. Say it needs a few days of traffic before the audit means anything, then re-run `llm-capture`.

## 4. finish

State what you wrote (`adapter.py`, `rows.jsonl`), the unit and input convention you used, where `model` came from if not the log, whether `prefix_hash` is content or structural, and the `usage_missing` count per route. Do not compute totals or averages yourself.

Then run the next skill, `llm-diagnose`.
