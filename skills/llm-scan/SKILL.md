---
name: llm-scan
description: Find every place a repo calls an LLM and write a route map (routes.json). Use when the user says "audit my LLM usage", "why is my LLM bill high", "make my LLM calls faster", "where do we call the model", "map our LLM calls", or starts any LLM cost or latency review. Run this first; llm-capture and llm-diagnose need its output.
---

# llm-scan

Read-only. Never edit, format, commit or run anything inside the target repo.

## 0. Setup

1. Detect which coding agent you are: Claude Code, or Codex (or any other coding agent). Read only the matching file, `delegation/claude.md` or `delegation/codex.md`, in this pack. It says which step goes to a cheap fast helper and which stays with you.
2. `<pack>` = the folder that holds `scripts/calc.py` (two levels above this file). `<repo>` = the target repo's folder name. All outputs go to `<pack>/work/<repo>/`. Create it. Never write into the target repo.

## 1. Find every call site

Search the whole repo (skip `node_modules`, `.venv`, `dist`, `build`, `.git`, lockfiles). Count all of these:

- SDK calls: any client library call that sends a prompt to a model (chat, messages, completions, responses, embeddings, streaming helpers, agent frameworks).
- CLI subprocess calls: an agent or model CLI run from code in non-interactive mode (a print flag such as `-p`, `exec`, `--prompt`), including long-lived warm workers and stream-json pipes.
- HTTP calls: direct requests to a model API URL, a gateway, a proxy, or a self-hosted endpoint.
- Decision, gate, classifier, router, reranker and judge models, even if tiny or cheap. They are LLM calls too.
- Warm-up, keepalive and health-check calls that hit a model: record them as routes (they often have no usage in the logs; see `usage_gaps`).
- Calls in tests, scripts, notebooks and cron jobs: list them, but mark `"live": false` if they never run in production.
- Non-LLM model calls (speech-to-text, text-to-speech, OCR, vision services billed per minute or per image): out of scope for pricing. List them with `"kind": "non_llm"` so the report can say they were seen and not priced.

Search for client imports, API hostnames, `model=` / `"model":` strings, `max_tokens`, `stream`, `cache_control`, and subprocess spawns of model CLIs. Then open each hit and read the function around it.

## 2. Record each route

One entry per call site. Route id = `relative/path.ext:function_name`; for a method, `relative/path.ext:Class.method`; use `<module>` if top level. Use the same id spelling everywhere (routes.json, rows, report).

| field | meaning |
|---|---|
| `id` | `file:function` or `file:Class.method` |
| `kind` | `sdk`, `cli`, `http`, `non_llm` |
| `provider` | as the code shows it, else `null` |
| `model` | the model string exactly as written, or the config key / env var that sets it (then also `model_source`). When one route's model varies at runtime, write `"varies"` and name the config or source in `model_source` |
| `streaming` | true / false / null |
| `cache_markers` | `explicit` (the code marks prompt cache points), `implicit` (no marks, but a stable prefix, warm process or provider default may cache it), `none` (nothing suggests caching), `unknown` |
| `max_tokens` | the number, or `null` if unset |
| `retries` | count and where (SDK default, wrapper, loop), or `0` |
| `user_waits` | true if a person is waiting on the answer (chat, voice, live UI); false for batch, background, cron; `"unknown"` if you cannot tell |
| `decision_model` | true for gates, routers, classifiers, judges |
| `decision_shaped` | `true` if the answer is a tiny verdict that feeds a code branch (an enum, a boolean, a label, a score) and the route runs per event or per item; `false` if the answer is free text or long structured output; `"unknown"` if you cannot tell. Record it for every route; calc also detects it from the logs (output p50 of 5 tokens or less on 50+ calls) |
| `tools` | where tool or function definitions are built and sent (file:function, and how many are sent per call if the code shows it), or `null` if the route sends none. Facts only; the numbers come from the logs |
| `live` | true; false if test-only; `"unknown"` if you cannot tell |
| `stateless` | true if every call stands alone (a per-event gate or classifier that sends no earlier turns); false if a conversation or memo grows across calls; `"unknown"` |
| `notes` | one short line, only facts you saw |

Use `null` (or `"unknown"` where the table allows it) when you cannot tell. Never guess a value.

## 3. Find the usage logs

Where does the app already record usage (tokens, cost, latency, time to first token, success)? Look for log files, JSONL, CSV, SQLite or database tables, tracing and metrics calls, and provider usage fields saved from responses. For each, record the path or table, the format, the field NAMES (never values), whether any field holds prompt or answer text (`has_text_fields`), and which route ids it covers. Do not open log values beyond the first few lines needed to learn the field names; do not copy any text from them.

Also note, by field NAME only, whether the logs record tool definitions or tool use per call (a count of tools sent, the size of the tool definitions in tokens, a count of tool calls in the response); `llm-capture` turns these into `tools_defined`, `tool_schema_tokens` and `tool_calls`. If the logs lack them, say so in `usage_gaps`.

Also record `usage_gaps`: short plain notes (one line each, facts only) where calls happen but the logs carry no token usage or the logged numbers cannot be trusted as is. Examples: "warm-up calls on route X are logged with no usage", "logged cost is a running total per process", "route Y is not logged at all". Counts are welcome ("seen N times") when you read them from field names and counts only.

## 4. Write `<pack>/work/<repo>/routes.json`

```json
{
  "repo": "<repo>",
  "root": "<absolute path of the target repo>",
  "scanned": "<YYYY-MM-DD>",
  "routes": [
    {"id": "path/file.py:Class.method", "kind": "cli", "provider": null, "model": "<string>", "model_source": null,
     "streaming": true, "cache_markers": "implicit", "max_tokens": null, "retries": 0,
     "user_waits": true, "decision_model": false, "decision_shaped": false, "tools": null, "live": true, "stateless": false, "notes": ""},
    {"id": "path/stt.py:transcribe", "kind": "non_llm", "live": true, "notes": "speech-to-text, not priced"}
  ],
  "usage_logs": [
    {"path": "<relative path or table>", "format": "jsonl", "fields": ["<names only>"],
     "has_text_fields": true, "covers_routes": ["path/file.py:Class.method"]}
  ],
  "usage_gaps": ["<one short note each>"]
}
```

## 5. Finish

Tell the user in a few lines: how many routes, which are the user-facing ones, which usage logs exist, any `usage_gaps`, and the next skill: `llm-capture`. Do not estimate costs or speeds here; numbers come only from `scripts/calc.py`.
