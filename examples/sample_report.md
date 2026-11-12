# $20.45-$54.41 a month (8.4-22.3% of spend) can go without changing model output, out of $244 a month; up to $113 more depends on evals
Synthetic data: every row is marked synthetic; no real system produced these numbers. Spend is a floor: 28 calls on 1 route have no token usage logged.

- The scope is stay: every action stays with the providers already in the export (caching, trimming, output caps, batching, failed-call fixes and a smaller model at the same provider). Models from other providers are not considered; run with `--scope open` to list them.
- The window is 14.0 days (2026-10-12 00:02 to 2026-10-26 00:01 UTC) with 10,944 calls and $114 priced spend: about $244 a month if the window is typical ($114 x 30 / 14.0 days).
- Savings that do not change model output come to $20.45-$54.41 a month (8.4-22.3% of monthly spend). A further $0-$113 a month (up to 46.4% of monthly spend) depends on evals and is unproven.
- MEASURED: cache reads cost $0.922 and cache writes cost $9.19 ($2.23 5-minute, $6.96 1-hour), 8.1% of spend, 10x the cache reads; 255 writes came after the first call of a session ($2.23). Detail by route and model below.
- TTFT p95 is 1,053 ms across 3,386 calls with a TTFT.
- First, turn on prompt caching on app/extract.py:parse_invoice: n=800 calls, $12.66-$18.98 a month after de-duplication, MECHANICAL.
- 10,972 rows read, 0 dropped, 0 on unpriced models, 28 flagged usage_missing (no token usage, not priced); prices dated 2026-11-12. The monthly ranges in the action table are de-duplicated and add up to the figures above.

## 6 actions are worth $20.45-$168 a month; first: turn on prompt caching

| rank | action | where | evidence | monthly range after de-dup | confidence | eval needed | effort |
|---|---|---|---|---|---|---|---|
| 1 | Turn on prompt caching | app/extract.py:parse_invoice | n=800 calls, 45.0% of spend | $12.66-$18.98 | MECHANICAL | no: compare billed cached tokens | Low |
| 2 | Stop paying for failed calls and retries | app/agent.py:run_task, app/extract.py:parse_invoice, app/chat.py:reply (+3 more) | n=467 calls, 14.5% of spend | $7.80-$35.44 | MEASURED | no: read the retry logs | Low to medium |
| 3 | Move work that can wait to batch pricing | app/extract.py:parse_invoice, app/agent.py:run_task, app/triage.py:needs_human (+1 more) | n=4,523 calls, 80.3% of spend | $0.00-$58.32 | HYPOTHESIS | ask who runs the route, then replay | Medium |
| 4 | Send easy calls to the next tier down | app/extract.py:parse_invoice, app/chat.py:reply, app/agent.py:run_task (+2 more) | n=2,173 calls, 19.3% of spend | $0.00-$42.99 | HYPOTHESIS | yes: replay 100-200 calls | Medium |
| 5 | Trim conversation history | app/chat.py:reply | n=2,871 calls, 12.6% of spend | $0.00-$11.46 | HYPOTHESIS | yes: replay 100-200 calls | Medium |
| 6 | Cap output length per model and route | app/extract.py:parse_invoice, app/chat.py:reply, app/agent.py:run_task (+1 more) | n=290 calls, 6.2% of spend | $0.00-$0.511 | HYPOTHESIS | yes: replay 100-200 calls | Low |
|  | Total (sum of the monthly column) |  |  | $20.45-$168 |  |  |  |

Ranked by the low end of the range, then the high end. Caching and failed-call waste do not change model output. Routing, trimming, output caps and batching depend on evals (floor $0). "Low evidence" marks a finding whose calls carry session_id and span fewer than 3 sessions: treat it as a lead, not a result.

## measured findings with no savings dollar

| finding | where | evidence | confidence | eval needed |
|---|---|---|---|---|
| Cut cache re-writes | app/chat.py:reply | 255 of 2,889 later calls re-wrote the cache, $2.23 in the window ($4.78 a month at window pace) | MEASURED | no: read why the cache is rewritten |

These routes already show cache reads or writes on at least half of their calls, so turning on caching is not the action. A re-write is a cache write after the first call of a session on the same route (session_id). The saving, if any, depends on why the cache is rewritten (a changing prefix, the time-to-live running out between calls, a cache break), which the export cannot show; no savings dollar is claimed and none is in the totals. To check: log the prefix hash on the re-writing calls and compare it with the previous call of the same session.

## unused tool schemas (MEASURED dollars, HYPOTHESIS action)

A route is judged on the calls that carry a tool schema and a tool-call count (at least 50 of them); on these routes the response called no tool on at least 90% of those calls, across 2 or more sessions (when session_id is logged). The dollars are tokens in the schema x the unused calls x the rate those tokens were billed at: the cached rate on a call whose cached tokens cover the schema, otherwise the uncached input rate (assumption: the schema is billed as plain input; a cache write would cost more). They are what the schemas cost, not a saving: removing a tool may change the model's behaviour, so the action is a HYPOTHESIS. Not in the action table or the totals (it overlaps caching and trimming).

| where | evidence | calls with no tool call | schema size (p50) | schema cost in window | dollars | action | eval needed |
|---|---|---|---|---|---|---|---|
| app/chat.py:reply | n=3,386 calls, 496 sessions | 97.4% of its schema-carrying calls (3,297) | 8 tools, 2,600 tokens | $4.47 ($9.59 a month) | MEASURED | HYPOTHESIS: drop or defer unused tool definitions | yes: replay 100-200 calls with the tools removed |

## spirals: tasks that loop and fail (MEASURED)

A spiral is a task (calls sharing a task_id on one route) whose calls or tokens exceed 2.5x its route's median task and that has at least 2 failed calls. A route needs 20 tasks before it is judged. The spend is read from the export; it overlaps the failed-call step and is in no total. On a route whose median task is 1 call, a spiral task also needs at least 4 calls. A spiral can be a hard task rather than a bug: read a few before fixing.

| where | evidence | median task | spiral tasks | spend in spirals | confidence |
|---|---|---|---|---|---|
| app/agent.py:run_task | n=139 tasks | 5.0 calls, 38,671 tokens | 11 (7.9% of tasks) | $15.77 (58.9% of route spend; $33.79 a month) | MEASURED |

## workload view: 1 interactive route with TTFT p95 of 1,053 ms; 5 back-office routes at <$0.0001-$0.211 per successful task

Each route gets the view that fits it (auto-detected). Interactive routes have TTFT or streamed calls; the rest are back-office.

### latency view

One call = one turn. No TTFT budget line: no --ttft-budget-ms given.

| route | calls | TTFT p50 | TTFT p95 | over TTFT budget | output speed p50 | output length p95 | cost per session | cost per turn |
|---|---|---|---|---|---|---|---|---|
| app/chat.py:reply | 3,386 | 652 ms | 1,053 ms | n/a | 63 tok/s | 373 tok | $0.045 (n=497 sessions) | $0.0066 (n=3,386 calls) |

#### app/chat.py:reply: TTFT by call position in session

Position is the order of the call within its session.

| call position | calls | TTFT p50 | TTFT p95 |
|---|---|---|---|
| 1 | 497 | 628 ms | 990 ms |
| 2-3 | 942 | 637 ms | 1,022 ms |
| 4-7 | 1,328 | 667 ms | 1,066 ms |
| 8+ | 619 | 679 ms | 1,092 ms |

#### app/chat.py:reply: TTFT by input size

| input size | range | calls | TTFT p50 | TTFT p95 |
|---|---|---|---|---|
| smallest third | 3,509 to 4,004 input tokens | 1,130 | 632 ms | 999 ms |
| middle third | 4,005 to 4,708 input tokens | 1,129 | 655 ms | 1,062 ms |
| largest third | 4,709 to 7,244 input tokens | 1,127 | 672 ms | 1,076 ms |

#### app/chat.py:reply: slowest 5% by TTFT

The tail is n=169 calls. Median input 4,408 tokens vs 4,316 for all calls on the route; median output 139 vs 147. Busiest UTC hours in the tail, as a multiple of each hour's share of all calls: 15:00 at 1.2x (n=24 tail calls), 14:00 at 1.1x (n=23 tail calls).

### back-office view

Unit = task (calls sharing a task_id; a call with no task id is its own task). Cost per successful task divides all route spend, failed tasks included, by successful tasks; cost per attempted task divides it by all tasks.

| route | tasks | tasks succeeded (proxy) | calls per task | cost per attempted task | cost per successful task | spend in failed tasks | costliest 5% of tasks | task duration p50 / p95 | batch-eligible |
|---|---|---|---|---|---|---|---|---|---|
| app/extract.py:parse_invoice | 732 | 98.5% of tasks (n=732) | 1.1 (n=814 calls) | $0.071 (n=732 tasks) | $0.072 (n=721 successful tasks) | $2.24 (4.3% of route spend) | 13.7% of route spend (top 37 of 732 tasks) | 14 s / 26 s | 100.0% of route spend |
| app/agent.py:run_task | 139 | 91.4% of tasks (n=139) | 6.9 (n=965 calls) | $0.193 (n=139 tasks) | $0.211 (n=127 successful tasks) | $9.01 (33.6% of route spend) | 42.3% of route spend (top 7 of 139 tasks) | 63 s / n/a (n=139, under 200) | 100.0% of route spend |
| app/triage.py:needs_human | 2,155 | 99.1% of tasks (n=2,155) | 1.0 (n=2,155 calls) | $0.0030 (n=2,155 tasks) | $0.0030 (n=2,135 successful tasks) | $0.058 (0.9% of route spend) | 10.4% of route spend (top 108 of 2,155 tasks) | 1 s / 1 s | 100.0% of route spend |
| app/summarize.py:summarise | 579 | 99.8% of tasks (n=579) | 1.0 (n=589 calls) | $0.011 (n=579 tasks) | $0.011 (n=578 successful tasks) | $0.013 (0.2% of route spend) | 8.5% of route spend (top 29 of 579 tasks) | 5 s / 9 s | 100.0% of route spend |
| app/gate.py:should_escalate | 3,035 | 99.7% of tasks (n=3,035) | 1.0 (n=3,035 calls) | <$0.0001 (n=3,035 tasks) | <$0.0001 (n=3,025 successful tasks) | $0.0003 (0.3% of route spend) | 9.8% of route spend (top 152 of 3,035 tasks) | n/a | 0.0% of route spend |

## 6 opportunities in detail

### 1. turn on prompt caching (MECHANICAL)

What we saw. 2 prefixes (by prefix_hash and provider) account for 3,847 repeat calls; 24.1% of calls already carry cached tokens (n=10,944 calls). It touches n=800 calls, 45.0% of window spend ($51.33), on app/extract.py:parse_invoice. 3,035 rows use a structural prefix_hash, not a hash of prompt text.

What it is worth. $12.66-$18.98 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history), MECHANICAL. Standalone it would be $19.45-$19.86 a month; only the after-earlier range is counted in the totals.

- Low end, app/extract.py:parse_invoice: 800 repeat calls that follow another call on the same prefix within the 300 s cache time-to-live x 6,000 prefix tokens moved to the cached rate x ($2.00 - $0.10) / 1M = $9.12; minus 14 cache writes paying a write premium of x1.25 on the input rate = $0.042. Net $9.08 in the window, $19.45 a month.
- High end, app/extract.py:parse_invoice: 813 repeat calls (every call after the first on its prefix, whatever the gap) x 6,000 prefix tokens moved to the cached rate x ($2.00 - $0.10) / 1M = $9.27; minus 1 cache writes paying a write premium of x1.25 on the input rate = $0.0030. Net $9.27 in the window, $19.86 a month.
- Skipped (the provider caches automatically, cache_mode implicit in prices.json, nothing to turn on): app/summarize.py:summarise.

How to check. Enable caching on one route for one day and compare billed cached tokens and TTFT with the day before. No replay is needed: caching does not change model output.

What would prove it wrong. Hits only count when the prefix is identical byte for byte. If a timestamp or user name sits inside the prefix, billed cached tokens will come in under this figure.

### 2. stop paying for failed calls and retries (MEASURED)

What we saw. 467 of 10,944 calls failed (4.3% of calls); 306 of the failures were retried. Failed calls cost $16.54 (14.5% of spend). The 131 tasks that ended in a failed last call cost $14.65 in total (12.9% of spend).

What it is worth. $7.80-$35.44 a month after the earlier waterfall steps (none, this step runs first), MEASURED. Standalone it would be $7.80-$35.44 a month; only the after-earlier range is counted in the totals.

- Low end: 306 failed calls were retried (a later call in the same task on the same model) and cost $14.55 in the window. Assumption A1: a quarter of that is avoidable. $14.55 x 0.25 = $3.64, x 30/14.0 = $7.80 a month.
- High end: all 467 failed calls cost $16.54 in the window, x 30/14.0 = $35.44 a month. Spend on the other calls inside failed tasks (131 failed tasks cost $14.65 in total, 12.9% of spend) is not counted; the back-office view shows it.

How to check. Read the retry logs: group 20 failed tasks by cause (timeout, rate limit, malformed output, validation) and fix the largest cause.

What would prove it wrong. Failures caused by provider outages or bad user input cannot be removed on your side; the avoidable share is an assumption, not a measurement.

### 3. move work that can wait to batch pricing (HYPOTHESIS)

What we saw. 4,523 calls (41.3% of calls) are not streamed and sit on routes with no TTFT. It touches n=4,523 calls, 80.3% of window spend ($91.51), on app/extract.py:parse_invoice, app/agent.py:run_task, app/triage.py:needs_human (+1 more).

What it is worth. $0.00-$58.32 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history, turn on prompt caching, cap output length per model and route), HYPOTHESIS. Standalone it would be $0.00-$98.05 a month; only the after-earlier range is counted in the totals.

- Low end is $0: nobody has confirmed that the work can wait.
- High end, app/extract.py:parse_invoice: 814 calls are not streamed and the route has no TTFT. They cost $52.17 at the current rates; at a 50% batch discount: $52.17 x 0.50 = $26.09 saved in the window, $55.90 a month.
- High end, app/agent.py:run_task: 965 calls are not streamed and the route has no TTFT. They cost $26.79 at the current rates; at a 50% batch discount: $26.79 x 0.50 = $13.39 saved in the window, $28.70 a month.
- High end, app/triage.py:needs_human: 2,155 calls are not streamed and the route has no TTFT. They cost $6.46 at the current rates; at a 50% batch discount: $6.46 x 0.50 = $3.23 saved in the window, $6.92 a month.

How to check. Ask whoever runs each route whether the work can wait up to 24 hours, then send a fixed, versioned set of 100-200 calls, stratified by route, through the batch API and compare with the live outputs on your own pass criteria.

What would prove it wrong. Only work that can wait for the batch window and has no user waiting qualifies; batch limits and availability differ by model.

### 4. send easy calls to the next tier down (HYPOTHESIS)

What we saw. 2,173 calls (19.9% of calls) meet the easy-call rule on 5 model-and-route groups with 200+ calls. It touches n=2,173 calls, 19.3% of window spend ($21.99), on app/extract.py:parse_invoice, app/chat.py:reply, app/agent.py:run_task (+2 more).

What it is worth. $0.00-$42.99 a month after the earlier waterfall steps (stop paying for failed calls and retries), HYPOTHESIS. Standalone it would be $0.00-$44.69 a month; only the after-earlier range is counted in the totals.

- Low end is $0: no call is known to be safe to move until the replay below passes.
- High end, app/extract.py:parse_invoice (claude-sonnet-5-5 -> claude-haiku-5-5): 216 of 814 calls have input <= 26,022 and output <= 700 tokens (the medians of this model and route). They use 4.51M uncached input, 0.00M cached input and 0.11M output tokens: now 4.51M x $2.00 + 0.00M x $0.10 + 0.11M x $10.00 (tokens in millions) = $10.13; at claude-haiku-5-5 ($0.10 / $0.01 / $0.50) = $0.507. Saving $9.62 in the window, $20.62 a month.
- High end, app/chat.py:reply (claude-sonnet-5-5 -> claude-haiku-5-5): 846 of 3,386 calls have input <= 4,316 and output <= 147 tokens (the medians of this model and route). They use 0.30M uncached input, 1.92M cached input and 0.08M output tokens: now 0.30M x $2.00 + 1.92M x $0.10 + 0.08M x $10.00 (tokens in millions) = $5.49; at claude-haiku-5-5 ($0.10 / $0.01 / $0.50) = $0.284. Saving $5.21 in the window, $11.16 a month. Cache-write tokens on these calls cost $3.89 at the current write rates; they are included in both totals and repriced at claude-haiku-5-5's write rates.
- High end, app/agent.py:run_task (claude-sonnet-5-5 -> claude-haiku-5-5): 252 of 965 calls have input <= 8,609 and output <= 218 tokens (the medians of this model and route). They use 1.69M uncached input, 0.00M cached input and 0.04M output tokens: now 1.69M x $2.00 + 0.00M x $0.10 + 0.04M x $10.00 (tokens in millions) = $3.80; at claude-haiku-5-5 ($0.10 / $0.01 / $0.50) = $0.190. Saving $3.61 in the window, $7.73 a month.

How to check. Replay a fixed, versioned set of 100-200 candidate calls, stratified by route, on the next tier down and grade the outputs with your own pass criteria.

What would prove it wrong. Short calls can still be hard. If the cheaper tier fails your criteria on more than a few percent of the replayed calls, the figure falls to $0 for that route.

### 5. trim conversation history (HYPOTHESIS)

What we saw. 2,871 calls (26.2% of calls) sit in sessions whose input grows beyond the first call. It touches n=2,871 calls, 12.6% of window spend ($14.41), on app/chat.py:reply.

What it is worth. $0.00-$11.46 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down), HYPOTHESIS. Standalone it would be $0.00-$12.79 a month; only the after-earlier range is counted in the totals.

- Low end is $0: whether the older turns can go is only known after the replay below.
- High end, app/chat.py:reply: 2,871 calls in 462 sessions carry 2,983,643 tokens above the first call of their session (input of call k minus input of call 1). Removing them at the input rates of each call: $14.41 -> $8.44, saving $5.97 in the window, $12.79 a month.

How to check. Replay a fixed, versioned set of 100-200 long-session calls, stratified by route, with history summarised or windowed and grade the answers with your own pass criteria.

What would prove it wrong. The growth may be retrieved documents or tool output that the answer needs, not old turns. This method cannot separate the two.

### 6. cap output length per model and route (HYPOTHESIS)

What we saw. 6 model-and-route groups have 200+ calls; only calls above their own p95 output are touched. It touches n=290 calls, 6.2% of window spend ($7.08), on app/extract.py:parse_invoice, app/chat.py:reply, app/agent.py:run_task (+1 more).

What it is worth. $0.00-$0.511 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history, turn on prompt caching), HYPOTHESIS. Standalone it would be $0.00-$0.912 a month; only the after-earlier range is counted in the totals.

- Low end is $0: the cap only helps if truncated answers are acceptable.
- High end, claude-sonnet-5-5 on app/extract.py:parse_invoice: p95 output is 1,676 tokens (n=814 calls). 41 calls are above it and emit 18,664 tokens over the cap, x $10.00 per 1M = $0.187 in the window, $0.400 a month.
- High end, claude-sonnet-5-5 on app/chat.py:reply: p95 output is 373 tokens (n=3,386 calls). 170 calls are above it and emit 17,460 tokens over the cap, x $10.00 per 1M = $0.175 in the window, $0.374 a month.
- High end, claude-sonnet-5-5 on app/agent.py:run_task: p95 output is 411 tokens (n=965 calls). 49 calls are above it and emit 3,924 tokens over the cap, x $10.00 per 1M = $0.039 in the window, $0.084 a month.

How to check. Replay the fixed, versioned set of 100-200 calls above the cap, stratified by route, with the limit set and grade completeness with your own pass criteria.

What would prove it wrong. A cap truncates long answers; for structured output a cut-off reply is a failed call. The value is mostly latency, not dollars.

## claude-sonnet-5-5 makes 47.2% of calls and 88.9% of spend; app/extract.py:parse_invoice is the costliest route at 45.8% of spend

| model | route | calls | uncached input | cached input | cache writes | output | spend | share |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | app/extract.py:parse_invoice | 814 | $45.66 | $0.00 | $0.00 | $6.51 | $52.17 | 45.8% of spend |
| claude-sonnet-5-5 | app/agent.py:run_task | 965 | $24.52 | $0.00 | $0.00 | $2.27 | $26.79 | 23.5% of spend |
| claude-sonnet-5-5 | app/chat.py:reply | 3,386 | $6.46 | $0.922 | $9.19 | $5.76 | $22.33 | 19.6% of spend |
| gpt-4o | app/triage.py:needs_human | 2,155 | $6.41 | $0.00 | $0.00 | $0.044 | $6.46 | 5.7% of spend |
| gpt-4o | app/summarize.py:summarise | 589 | $4.62 | $0.00 | $0.00 | $1.48 | $6.09 | 5.3% of spend |
| jev-1.14.0 | app/gate.py:should_escalate | 3,035 | $0.094 | $0.00 | $0.00 | $0.00 | $0.094 | 0.1% of spend |
| Total |  | 10,944 | $87.76 | $0.922 | $9.19 | $16.06 | $114 | 100% |

## cache in use (MEASURED): 8% of spend is cache writes, 10x cache reads

Read directly from the cache columns, priced at the rates in prices.json; no prefix_hash needed. This section states what the cache cost and returned. It carries no savings dollar: a saving needs a mechanism (for example a stable prefix), which the action table prices only when prefix_hash is present.

| route | model | calls | cache read $ | 5-minute write $ | 1-hour write $ | write $ vs read $ | share of spend on writes | writes after the first call of a session |
|---|---|---|---|---|---|---|---|---|
| app/chat.py:reply | claude-sonnet-5-5 | 3,386 | $0.922 | $2.23 | $6.96 | 10x | 41.1% of its spend | 255 of 2,889 later calls, $2.23 |
| Total |  | 3,386 | $0.922 | $2.23 | $6.96 | 10x | 8.1% of all spend | 255 of 2,889 later calls, $2.23 |

Writes after the first call of a session are re-writes (churn): the cache was written again inside a session on the same route (session_id; none counted on stateless routes).

## calls with no token usage logged: spend is a floor

These rows are flagged usage_missing. They are counted here and left out of every spend and savings figure; the calls happened, their cost is unknown.

| route | calls | models seen |
|---|---|---|
| app/warmup.py:keepalive | 28 | claude-sonnet-5-5 |

## scan-only findings (UNMEASURED, no dollars)

From the scan's routes.json, not from the export. Nothing here is priced or in any dollar figure above.

- Usage gap: warm-up calls on app/warmup.py:keepalive are logged with no token usage.
- app/warmup.py:keepalive (live: yes): no priced rows in the export; 28 calls were seen with no token usage logged, so its cost is unknown.
- 1 test-only route with no rows (not live): tests/test_chat.py:test_reply.
- Out of scope (not LLM calls, kind non_llm): app/voice.py:transcribe.

## method and limits: 14.0 days of data, projected to 30 days

- Monthly figures are window spend x 30 / window days ($114 x 30 / 14.0). Under 7 days of data the projection is flagged.
- `prices.json` is dated 2026-11-12 with status "list prices read from the public pricing pages on 2026-11-12; cache time-to-live, cache minimum-size and implicit-cache terms are not on those pages and are not verified". Verify every price field, cache term and batch discount against the provider pricing pages before acting on a dollar figure.
- input_tokens includes cached_input_tokens, cache_write_tokens and cache_write_1h_tokens. Spend = uncached input x input rate + cached input x cached rate + cache writes (5-minute at the provider's write multiplier, 1-hour at 2x) x input rate + output x output rate.
- Each finding carries one label. MEASURED: the size is read directly from the export. MECHANICAL: follows from provider price rules and observed timings and does not change model output. HYPOTHESIS: needs proving on your calls with an eval.
- Each range comes from named assumptions, not a haircut. Low end: failed-call waste = 25% of retried failed-call spend (A1); caching = repeats inside the provider cache time-to-live, net of the write premium, per prefix and never below $0; all other actions $0. High end: failed-call waste = all failed-call spend; caching = every repeat after the first on each prefix; routing = short calls (input and output at or under the route medians) at the same provider's next tier down (when several models share that tier, the one with the lowest input price in prices.json); trimming = input above the first call of the session at the input rate; caps = output above the p95 of its model and route at the output rate; batching = non-streamed calls on routes with no TTFT at the provider's batch discount.
- Steps run in a fixed order: failed-task waste, routing, trimming, caching, output caps, batching. Each step is computed on the spend the earlier steps left. The totals sum only the after-earlier figures. The waterfall runs twice, once with every step at its low end and once at its high end; a row shows the smaller and larger of its two after-earlier figures, so a later step can show a lower low end than the chains alone suggest. The two buckets use the same waterfall: the caching figure assumes routing and trimming were adopted, and is worth more if they are not.
- A task succeeds when its last call succeeded. This is a proxy: a call can succeed technically and still give a wrong answer.
- `--scope stay` (default) keeps every action inside the providers in the export. `--scope open` adds the "other providers" section: candidates from prices.json by `class`, at list price, always HYPOTHESIS with a $0 low end, outside every total. `class` is a hand-set price band in prices.json (decision, small, mid, frontier), not a quality claim. A route's spend there is re-priced token for token with this export's token counts (providers' tokenizers differ, so a real bill can differ); cached tokens are priced at the input rate for a provider whose cache terms are unverified. A route needs 200 priced calls before candidates are listed. The candidates in one route are alternatives, not additions. A candidate that adds calls (a decision-model gate) is shown net of those calls, priced from prices.json. The share of calls the gate cannot decide (they go on to the current model) is yours to measure: pass it as `--gate-pass-through FRACTION`. Without it the gate figure is the ceiling that assumes the gate decides every call, printed with the break-even pass-through share (the share at which the net saving is zero).
- A finding whose calls carry session_id and span fewer than 3 sessions is marked low evidence. Calls with no session_id leave the session count unknown, which is not marked.
- Tool-schema and spiral figures are MEASURED spend, outside the waterfall and the totals. Tool-schema dollars use the cached rate when the call's cached tokens cover the schema and the uncached input rate otherwise, and a route needs 50 calls that carry a schema and a tool-call count; a spiral is a task above 2.5x its route's median calls or tokens with 2 or more failed calls (routes with under 20 tasks are not judged; on a route whose median task is 1 call, a spiral task needs 4 or more calls).
- No p95 is printed for groups under 200 calls; no caching dollars without a prefix_hash column; routing only goes to the same provider's next tier down (the lowest input price among models sharing that tier); a provider marked cache_mode implicit in prices.json caches by itself, so no prompt-caching action is recommended for its routes; calls on unpriced models are excluded from every figure.
- 10,972 rows read; 0 dropped (none); 0 rows on unpriced models; 0 priced rows have no usable timestamp.
- 28 calls on 1 route flagged usage_missing: counted, not priced, so spend is a floor.
- Calls flagged stateless are skipped by the trimming and session-growth steps and by session views: each call stands alone, so a later call carries no history to cut.
- 3,035 rows carry a structural prefix_hash (route, model and process generation), not a hash of the prompt text. The caching figure assumes the prefix is stable across calls with the same hash; billed cache reads are the check.

## next step: a pilot on app/extract.py:parse_invoice in three steps

1. Collect an export of 7-30 days with route, prefix_hash, success and task_id columns and rerun.
2. Enable prompt caching on app/extract.py:parse_invoice for one day and compare the billed result with the day before.
3. Replay a fixed, versioned set of 100-200 calls stratified by route to test: batch the work that can wait, graded with your own pass criteria.

## appendix: reference tables and definitions

### token percentiles by route

| route | calls | input p50 | input p95 | output p50 | output p95 |
|---|---|---|---|---|---|
| app/extract.py:parse_invoice | 814 | 26,022 | 45,191 | 700 | 1,676 |
| app/agent.py:run_task | 965 | 8,609 | 33,883 | 218 | 411 |
| app/chat.py:reply | 3,386 | 4,316 | 5,844 | 147 | 373 |
| app/triage.py:needs_human | 2,155 | 1,094 | 2,149 | 2 | 3 |
| app/summarize.py:summarise | 589 | 2,943 | 4,648 | 233 | 448 |
| app/gate.py:should_escalate | 3,035 | 688 | 1,231 | 0 | 0 |

### five costliest tasks (ids are sha256 hashes)

| task | route | calls | cost | share of spend |
|---|---|---|---|---|
| cea5c92e202c | app/agent.py:run_task | 36 | $1.84 | 1.6% of spend |
| c7c522d582d1 | app/agent.py:run_task | 34 | $1.69 | 1.5% of spend |
| a4ce3275eb7d | app/agent.py:run_task | 34 | $1.69 | 1.5% of spend |
| 10608753915c | app/agent.py:run_task | 34 | $1.68 | 1.5% of spend |
| 6ce4705178d7 | app/agent.py:run_task | 33 | $1.59 | 1.4% of spend |

### latency per model

| model | calls | latency p50 | latency p95 | TTFT p50 | TTFT p95 |
|---|---|---|---|---|---|
| claude-sonnet-5-5 | 5,165 | 3,692 ms | 17,239 ms | 652 ms | 1,053 ms |
| jev-1.14.0 | 3,035 | 125 ms | 156 ms | n/a | n/a (n=0, under 200) |
| gpt-4o | 2,744 | 554 ms | 6,559 ms | n/a | n/a (n=0, under 200) |

### per-prefix table

| prefix | route | calls | prefix tokens | calls with cached tokens | repeats inside cache TTL |
|---|---|---|---|---|---|
| 4d6292de6096 | app/gate.py:should_escalate | 3,035 | 250 | 0.0% of its calls | 55.4% of repeats (n=3,034) |
| fda4e55cbc8a | app/extract.py:parse_invoice | 814 | 6,000 | 0.0% of its calls | 98.4% of repeats (n=813) |

### candidate-call definitions

| term | definition |
|---|---|
| Routing candidate | a call on a model and route group with 200+ calls whose provider has a lower tier, with input and output tokens at or under that group's medians |
| Trimming candidate | a call that is not the first of its session on its route, in a session with 3+ calls there; excess = its input tokens minus the first call's |
| Output-cap candidate | a call above the p95 output of its model and route group (200+ calls) |
| Batching candidate | a call that is not streamed (streamed column, else no TTFT) on a provider with a batch discount |
| Retry | a failed call followed by a later call in the same task on the same model |
| Cache hit (low end) | a call within the provider's cache time-to-live of the previous call on the same prefix_hash and provider, with the prefix at or above the provider's minimum cacheable tokens |
