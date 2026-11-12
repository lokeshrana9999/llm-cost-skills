# $15.73-$34.10 a month (9.1-19.7% of spend) can go without changing model output, out of $173 a month; up to $82.76 more depends on evals
Synthetic data: every row is marked synthetic; no real system produced these numbers. **Spend is a floor: 28 calls on 1 route have no token usage logged.**

- **Window:** 14.0 days (2026-10-12 00:02 to 2026-10-26 00:01 UTC), 7,824 calls, $80.69 priced spend; about $173 a month if the window is typical ($80.69 x 30 / 14.0 days).
- **Savings that do not change model output:** $15.73-$34.10 a month (9.1-19.7% of monthly spend). **Further, depends on evals:** $0-$82.76 a month (up to 47.9% of monthly spend), unproven.
- **Cache in use (MEASURED):** cache reads $0.922; cache writes $9.19 ($2.23 5-minute, $6.96 1-hour) = 11.4% of spend, 10x the cache reads; 255 writes came after the first call of a session ($2.23). Detail by route and model below.
- **Speed:** TTFT p95 is 1,053 ms across 3,386 calls with a TTFT.
- **Do first:** turn on prompt caching on app/extract.py:parse_invoice: n=800 calls, $12.66-$18.98 a month after de-duplication, MECHANICAL.
- **Data:** 7,852 rows read, 0 dropped, 0 on unpriced models, 28 flagged usage_missing (no token usage, not priced); prices dated 2026-11-11. The monthly ranges in the action table are de-duplicated and add up to the figures above.

## 6 actions are worth $15.73-$117 a month after de-duplication; first: turn on prompt caching

| rank | action | where | evidence | monthly range after de-dup | confidence | eval needed | effort |
|---|---|---|---|---|---|---|---|
| 1 | Turn on prompt caching | app/extract.py:parse_invoice | n=800 calls, 63.6% of spend | $12.66-$18.98 | MECHANICAL | no: compare billed cached tokens | Low |
| 2 | Stop paying for failed calls and retries | app/extract.py:parse_invoice, app/chat.py:reply, app/summarize.py:summarise (+1 more) | n=221 calls, 8.7% of spend | $3.07-$15.13 | MEASURED | no: read the retry logs | Low to medium |
| 3 | Move work that can wait to batch pricing | app/extract.py:parse_invoice, app/summarize.py:summarise | n=1,403 calls, 72.2% of spend | $0.00-$37.90 | HYPOTHESIS | ask who runs the route, then replay | Medium |
| 4 | Send easy calls to the next tier down | app/extract.py:parse_invoice, app/chat.py:reply, app/summarize.py:summarise | n=1,199 calls, 20.7% of spend | $0.00-$32.95 | HYPOTHESIS | yes: replay 100-200 calls | Medium |
| 5 | Trim conversation history | app/chat.py:reply | n=2,871 calls, 17.9% of spend | $0.00-$11.46 | HYPOTHESIS | yes: replay 100-200 calls | Medium |
| 6 | Cap output length per model and route | app/extract.py:parse_invoice, app/chat.py:reply, app/summarize.py:summarise | n=241 calls, 6.9% of spend | $0.00-$0.448 | HYPOTHESIS | yes: replay 100-200 calls | Low |
|  | **Total** (sum of the monthly column) |  |  | **$15.73-$117** |  |  |  |

Ranked by the low end of the range, then the high end. Does not change model output: caching, failed-call waste. Depends on evals (floor $0): routing, trimming, output caps, batching.

## Measured findings with no savings dollar

| finding | where | evidence | confidence | eval needed |
|---|---|---|---|---|
| Cut cache re-writes | app/chat.py:reply | 255 of 2,889 later calls re-wrote the cache, $2.23 in the window ($4.78 a month at window pace) | MEASURED | no: read why the cache is rewritten |

These routes already show cache reads or writes on at least half of their calls, so turning on caching is not the action. A re-write is a cache write after the first call of a session on the same route (session_id). The saving, if any, depends on why the cache is rewritten (a changing prefix, the time-to-live running out between calls, a cache break), which the export cannot show; no savings dollar is claimed and none is in the totals. To check: log the prefix hash on the re-writing calls and compare it with the previous call of the same session.

## Workload view: 1 interactive route with TTFT p95 of 1,053 ms; 3 back-office routes at <$0.0001-$0.072 per successful task

Each route gets the view that fits it (auto-detected). Interactive routes have TTFT or streamed calls; the rest are back-office.

### Latency view

One call = one turn. No TTFT budget line: no --ttft-budget-ms given.

| route | calls | TTFT p50 | TTFT p95 | over TTFT budget | output speed p50 | output length p95 | cost per session | cost per turn |
|---|---|---|---|---|---|---|---|---|
| app/chat.py:reply | 3,386 | 652 ms | 1,053 ms | n/a | 63 tok/s | 373 tok | $0.045 (n=497 sessions) | $0.0066 (n=3,386 calls) |

**app/chat.py:reply: TTFT by call position in session** (position = order of the call within its session)

| call position | calls | TTFT p50 | TTFT p95 |
|---|---|---|---|
| 1 | 497 | 628 ms | 990 ms |
| 2-3 | 942 | 637 ms | 1,022 ms |
| 4-7 | 1,328 | 667 ms | 1,066 ms |
| 8+ | 619 | 679 ms | 1,092 ms |

**app/chat.py:reply: TTFT by input size**

| input size | range | calls | TTFT p50 | TTFT p95 |
|---|---|---|---|---|
| smallest third | 3,509 to 4,004 input tokens | 1,130 | 632 ms | 999 ms |
| middle third | 4,005 to 4,708 input tokens | 1,129 | 655 ms | 1,062 ms |
| largest third | 4,709 to 7,244 input tokens | 1,127 | 672 ms | 1,076 ms |

**app/chat.py:reply: slowest 5% by TTFT** (n=169 calls). Median input 4,408 tokens vs 4,316 for all calls on the route; median output 139 vs 147. Busiest UTC hours in the tail, as a multiple of each hour's share of all calls: 15:00 at 1.2x (n=24 tail calls), 14:00 at 1.1x (n=23 tail calls).

### Back-office view

Unit = task (calls sharing a task_id; a call with no task id is its own task). Cost per successful task divides all route spend, failed tasks included, by successful tasks; cost per attempted task divides it by all tasks.

| route | tasks | tasks succeeded (proxy) | calls per task | cost per attempted task | cost per successful task | spend in failed tasks | costliest 5% of tasks | task duration p50 / p95 | batch-eligible |
|---|---|---|---|---|---|---|---|---|---|
| app/extract.py:parse_invoice | 732 | 98.5% of tasks (n=732) | 1.1 (n=814 calls) | $0.071 (n=732 tasks) | $0.072 (n=721 successful tasks) | $2.24 (4.3% of route spend) | 13.7% of route spend (top 37 of 732 tasks) | 14 s / 26 s | 100.0% of route spend |
| app/summarize.py:summarise | 579 | 99.8% of tasks (n=579) | 1.0 (n=589 calls) | $0.011 (n=579 tasks) | $0.011 (n=578 successful tasks) | $0.013 (0.2% of route spend) | 8.5% of route spend (top 29 of 579 tasks) | 5 s / 9 s | 100.0% of route spend |
| app/gate.py:should_escalate | 3,035 | 99.7% of tasks (n=3,035) | 1.0 (n=3,035 calls) | <$0.0001 (n=3,035 tasks) | <$0.0001 (n=3,025 successful tasks) | $0.0003 (0.3% of route spend) | 9.8% of route spend (top 152 of 3,035 tasks) | n/a | 0.0% of route spend |

## The 6 opportunities in detail: what we saw, what it is worth, how to check, what would prove it wrong

### 1. Turn on prompt caching (MECHANICAL)

**What we saw.** 2 prefixes (by prefix_hash and provider) account for 3,847 repeat calls; 33.7% of calls already carry cached tokens (n=7,824 calls). It touches n=800 calls, 63.6% of window spend ($51.33), on app/extract.py:parse_invoice. 3,035 rows use a structural prefix_hash, not a hash of prompt text.

**What it is worth.** $12.66-$18.98 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history), MECHANICAL. Standalone it would be $19.45-$19.86 a month; only the after-earlier range is counted in the totals.

- Low end, app/extract.py:parse_invoice: 800 repeat calls that follow another call on the same prefix within the 300 s cache time-to-live x 6,000 prefix tokens moved to the cached rate x ($2.00 - $0.10) / 1M = $9.12; minus 14 cache writes paying a write premium of x1.25 on the input rate = $0.042. Net $9.08 in the window, $19.45 a month.
- High end, app/extract.py:parse_invoice: 813 repeat calls (every call after the first on its prefix, whatever the gap) x 6,000 prefix tokens moved to the cached rate x ($2.00 - $0.10) / 1M = $9.27; minus 1 cache writes paying a write premium of x1.25 on the input rate = $0.0030. Net $9.27 in the window, $19.86 a month.
- Skipped (the provider caches automatically, cache_mode implicit in prices.json, nothing to turn on): app/summarize.py:summarise.

**How to check.** Enable caching on one route for one day and compare billed cached tokens and TTFT with the day before. No replay is needed: caching does not change model output.

**What would prove it wrong.** Hits only count when the prefix is identical byte for byte. If a timestamp or user name sits inside the prefix, billed cached tokens will come in under this figure.

### 2. Stop paying for failed calls and retries (MEASURED)

**What we saw.** 221 of 7,824 calls failed (2.8% of calls); 92 of the failures were retried. Failed calls cost $7.06 (8.7% of spend). The 119 tasks that ended in a failed last call cost $5.64 in total (7.0% of spend).

**What it is worth.** $3.07-$15.13 a month after the earlier waterfall steps (none, this step runs first), MEASURED. Standalone it would be $3.07-$15.13 a month; only the after-earlier range is counted in the totals.

- Low end: 92 failed calls were retried (a later call in the same task on the same model) and cost $5.74 in the window. Assumption A1: a quarter of that is avoidable. $5.74 x 0.25 = $1.43, x 30/14.0 = $3.07 a month.
- High end: all 221 failed calls cost $7.06 in the window, x 30/14.0 = $15.13 a month. Spend on the other calls inside failed tasks (119 failed tasks cost $5.64 in total, 7.0% of spend) is not counted; the back-office view shows it.

**How to check.** Read the retry logs: group 20 failed tasks by cause (timeout, rate limit, malformed output, validation) and fix the largest cause.

**What would prove it wrong.** Failures caused by provider outages or bad user input cannot be removed on your side; the avoidable share is an assumption, not a measurement.

### 3. Move work that can wait to batch pricing (HYPOTHESIS)

**What we saw.** 1,403 calls (17.9% of calls) are not streamed and sit on routes with no TTFT. It touches n=1,403 calls, 72.2% of window spend ($58.27), on app/extract.py:parse_invoice, app/summarize.py:summarise.

**What it is worth.** $0.00-$37.90 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history, turn on prompt caching, cap output length per model and route), HYPOTHESIS. Standalone it would be $0.00-$62.43 a month; only the after-earlier range is counted in the totals.

- Low end is $0: nobody has confirmed that the work can wait.
- High end, app/extract.py:parse_invoice: 814 calls are not streamed and the route has no TTFT. They cost $52.17 at the current rates; at a 50% batch discount: $52.17 x 0.50 = $26.09 saved in the window, $55.90 a month.
- High end, app/summarize.py:summarise: 589 calls are not streamed and the route has no TTFT. They cost $6.09 at the current rates; at a 50% batch discount: $6.09 x 0.50 = $3.05 saved in the window, $6.53 a month.

**How to check.** Ask whoever runs each route whether the work can wait up to 24 hours, then send a fixed, versioned set of 100-200 calls, stratified by route, through the batch API and compare with the live outputs on your own pass criteria.

**What would prove it wrong.** Only work that can wait for the batch window and has no user waiting qualifies; batch limits and availability differ by model.

### 4. Send easy calls to the next tier down (HYPOTHESIS)

**What we saw.** 1,199 calls (15.3% of calls) meet the easy-call rule on 3 model-and-route groups with 200+ calls. It touches n=1,199 calls, 20.7% of window spend ($16.71), on app/extract.py:parse_invoice, app/chat.py:reply, app/summarize.py:summarise.

**What it is worth.** $0.00-$32.95 a month after the earlier waterfall steps (stop paying for failed calls and retries), HYPOTHESIS. Standalone it would be $0.00-$33.99 a month; only the after-earlier range is counted in the totals.

- Low end is $0: no call is known to be safe to move until the replay below passes.
- High end, app/extract.py:parse_invoice (claude-sonnet-5-5 -> claude-haiku-5-5): 216 of 814 calls have input <= 26,022 and output <= 700 tokens (the medians of this model and route). They use 4.51M uncached input, 0.00M cached input and 0.11M output tokens: now 4.51M x $2.00 + 0.00M x $0.10 + 0.11M x $10.00 (tokens in millions) = $10.13; at claude-haiku-5-5 ($0.10 / $0.01 / $0.50) = $0.507. Saving $9.62 in the window, $20.62 a month.
- High end, app/chat.py:reply (claude-sonnet-5-5 -> claude-haiku-5-5): 846 of 3,386 calls have input <= 4,316 and output <= 147 tokens (the medians of this model and route). They use 0.30M uncached input, 1.92M cached input and 0.08M output tokens: now 0.30M x $2.00 + 1.92M x $0.10 + 0.08M x $10.00 (tokens in millions) = $5.49; at claude-haiku-5-5 ($0.10 / $0.01 / $0.50) = $0.284. Saving $5.21 in the window, $11.16 a month. Cache-write tokens on these calls cost $3.89 at the current write rates; they are included in both totals and repriced at claude-haiku-5-5's write rates.
- High end, app/summarize.py:summarise (gpt-4o -> gpt-4o-mini): 137 of 589 calls have input <= 2,943 and output <= 233 tokens (the medians of this model and route). They use 0.35M uncached input, 0.00M cached input and 0.02M output tokens: now 0.35M x $2.50 + 0.00M x $1.25 + 0.02M x $10.00 (tokens in millions) = $1.09; at gpt-4o-mini ($0.15 / $0.075 / $0.60) = $0.066. Saving $1.03 in the window, $2.20 a month.

**How to check.** Replay a fixed, versioned set of 100-200 candidate calls, stratified by route, on the next tier down and grade the outputs with your own pass criteria.

**What would prove it wrong.** Short calls can still be hard. If the cheaper tier fails your criteria on more than a few percent of the replayed calls, the figure falls to $0 for that route.

### 5. Trim conversation history (HYPOTHESIS)

**What we saw.** 2,871 calls (36.7% of calls) sit in sessions whose input grows beyond the first call. It touches n=2,871 calls, 17.9% of window spend ($14.41), on app/chat.py:reply.

**What it is worth.** $0.00-$11.46 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down), HYPOTHESIS. Standalone it would be $0.00-$12.79 a month; only the after-earlier range is counted in the totals.

- Low end is $0: whether the older turns can go is only known after the replay below.
- High end, app/chat.py:reply: 2,871 calls in 462 sessions carry 2,983,643 tokens above the first call of their session (input of call k minus input of call 1). Removing them at the input rates of each call: $14.41 -> $8.44, saving $5.97 in the window, $12.79 a month.

**How to check.** Replay a fixed, versioned set of 100-200 long-session calls, stratified by route, with history summarised or windowed and grade the answers with your own pass criteria.

**What would prove it wrong.** The growth may be retrieved documents or tool output that the answer needs, not old turns. This method cannot separate the two.

### 6. Cap output length per model and route (HYPOTHESIS)

**What we saw.** 4 model-and-route groups have 200+ calls; only calls above their own p95 output are touched. It touches n=241 calls, 6.9% of window spend ($5.57), on app/extract.py:parse_invoice, app/chat.py:reply, app/summarize.py:summarise.

**What it is worth.** $0.00-$0.448 a month after the earlier waterfall steps (stop paying for failed calls and retries, send easy calls to the next tier down, trim conversation history, turn on prompt caching), HYPOTHESIS. Standalone it would be $0.00-$0.828 a month; only the after-earlier range is counted in the totals.

- Low end is $0: the cap only helps if truncated answers are acceptable.
- High end, claude-sonnet-5-5 on app/extract.py:parse_invoice: p95 output is 1,676 tokens (n=814 calls). 41 calls are above it and emit 18,664 tokens over the cap, x $10.00 per 1M = $0.187 in the window, $0.400 a month.
- High end, claude-sonnet-5-5 on app/chat.py:reply: p95 output is 373 tokens (n=3,386 calls). 170 calls are above it and emit 17,460 tokens over the cap, x $10.00 per 1M = $0.175 in the window, $0.374 a month.
- High end, gpt-4o on app/summarize.py:summarise: p95 output is 448 tokens (n=589 calls). 30 calls are above it and emit 2,507 tokens over the cap, x $10.00 per 1M = $0.025 in the window, $0.054 a month.

**How to check.** Replay the fixed, versioned set of 100-200 calls above the cap, stratified by route, with the limit set and grade completeness with your own pass criteria.

**What would prove it wrong.** A cap truncates long answers; for structured output a cut-off reply is a failed call. The value is mostly latency, not dollars.

## claude-sonnet-5-5 makes 53.7% of calls and 92.3% of spend; app/extract.py:parse_invoice is the costliest route at 64.7% of spend

| model | route | calls | uncached input | cached input | cache writes | output | spend | share |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | app/extract.py:parse_invoice | 814 | $45.66 | $0.00 | $0.00 | $6.51 | $52.17 | 64.7% of spend |
| claude-sonnet-5-5 | app/chat.py:reply | 3,386 | $6.46 | $0.922 | $9.19 | $5.76 | $22.33 | 27.7% of spend |
| gpt-4o | app/summarize.py:summarise | 589 | $4.62 | $0.00 | $0.00 | $1.48 | $6.09 | 7.6% of spend |
| jev-1.14.0 | app/gate.py:should_escalate | 3,035 | $0.094 | $0.00 | $0.00 | $0.00 | $0.094 | 0.1% of spend |
| **Total** |  | 7,824 | $56.83 | $0.922 | $9.19 | $13.75 | $80.69 | 100% |

## Cache in use (MEASURED): 11% of spend is cache writes, 10x cache reads

Read directly from the cache columns, priced at the rates in prices.json; no prefix_hash needed. This section states what the cache cost and returned. It carries no savings dollar: a saving needs a mechanism (for example a stable prefix), which the action table prices only when prefix_hash is present.

| route | model | calls | cache read $ | 5-minute write $ | 1-hour write $ | write $ vs read $ | share of spend on writes | writes after the first call of a session |
|---|---|---|---|---|---|---|---|---|
| app/chat.py:reply | claude-sonnet-5-5 | 3,386 | $0.922 | $2.23 | $6.96 | 10x | 41.1% of its spend | 255 of 2,889 later calls, $2.23 |
| **Total** |  | 3,386 | $0.922 | $2.23 | $6.96 | 10x | 11.4% of all spend | 255 of 2,889 later calls, $2.23 |

Writes after the first call of a session are re-writes (churn): the cache was written again inside a session on the same route (session_id; none counted on stateless routes).

## Calls with no token usage logged: spend is a floor

These rows are flagged usage_missing. They are counted here and left out of every spend and savings figure; the calls happened, their cost is unknown.

| route | calls | models seen |
|---|---|---|
| app/warmup.py:keepalive | 28 | claude-sonnet-5-5 |

## Scan-only findings (UNMEASURED, no dollars)

From the scan's routes.json, not from the export. Nothing here is priced or in any dollar figure above.

- Usage gap: warm-up calls on app/warmup.py:keepalive are logged with no token usage.
- app/warmup.py:keepalive (live: yes): no priced rows in the export; 28 calls were seen with no token usage logged, so its cost is unknown.
- 1 test-only route with no rows (not live): tests/test_chat.py:test_reply.
- Out of scope (not LLM calls, kind non_llm): app/voice.py:transcribe.

## Method and limits: 14.0 days of data, projected to 30 days

- **Projection.** Monthly = window spend x 30 / window days ($80.69 x 30 / 14.0). Under 7 days of data the projection is flagged.
- **Prices.** `prices.json` is dated 2026-11-11 with status "unverified, edit before use". Verify every price field, cache term and batch discount against the provider pricing pages before acting on a dollar figure.
- **Tokens.** input_tokens includes cached_input_tokens, cache_write_tokens and cache_write_1h_tokens. Spend = uncached input x input rate + cached input x cached rate + cache writes (5-minute at the provider's write multiplier, 1-hour at 2x) x input rate + output x output rate.
- **Labels.** MEASURED: the size is read directly from the export. MECHANICAL: follows from provider price rules and observed timings and does not change model output. HYPOTHESIS: needs proving on your calls with an eval.
- **Ranges.** Each range comes from named assumptions, not a haircut. Low end: failed-call waste = 25% of retried failed-call spend (A1); caching = repeats inside the provider cache time-to-live, net of the write premium, per prefix and never below $0; all other actions $0. High end: failed-call waste = all failed-call spend; caching = every repeat after the first on each prefix; routing = short calls (input and output at or under the route medians) at the same provider's next tier down (when several models share that tier, the one with the lowest input price in prices.json); trimming = input above the first call of the session at the input rate; caps = output above the p95 of its model and route at the output rate; batching = non-streamed calls on routes with no TTFT at the provider's batch discount.
- **Waterfall.** Steps run in a fixed order: failed-task waste, routing, trimming, caching, output caps, batching. Each step is computed on the spend the earlier steps left. The totals sum only the after-earlier figures. The waterfall runs twice, once with every step at its low end and once at its high end; a row shows the smaller and larger of its two after-earlier figures, so a later step can show a lower low end than the chains alone suggest. The two buckets use the same waterfall: the caching figure assumes routing and trimming were adopted, and is worth more if they are not.
- **Success.** A task succeeds when its last call succeeded. This is a proxy: a call can succeed technically and still give a wrong answer.
- **Limits.** No p95 is printed for groups under 200 calls; no caching dollars without a prefix_hash column; routing only goes to the same provider's next tier down (the lowest input price among models sharing that tier); a provider marked cache_mode implicit in prices.json caches by itself, so no prompt-caching action is recommended for its routes; calls on unpriced models are excluded from every figure.
- **Data quality.** 7,852 rows read; 0 dropped (none); 0 rows on unpriced models; 0 priced rows have no usable timestamp.
- **Usage missing.** 28 calls on 1 route flagged usage_missing: counted, not priced, so spend is a floor.
- **Stateless routes.** Calls flagged stateless are skipped by the trimming and session-growth steps and by session views: each call stands alone, so a later call carries no history to cut.
- **Prefix hash.** 3,035 rows carry a structural prefix_hash (route, model and process generation), not a hash of the prompt text. The caching figure assumes the prefix is stable across calls with the same hash; billed cache reads are the check.

## Next step: a pilot on app/extract.py:parse_invoice in three steps

1. Collect an export of 7-30 days with route, prefix_hash, success and task_id columns and rerun.
2. Enable prompt caching on app/extract.py:parse_invoice for one day and compare the billed result with the day before.
3. Replay a fixed, versioned set of 100-200 calls stratified by route to test: batch the work that can wait, graded with your own pass criteria.

## Appendix

### Token percentiles by route

| route | calls | input p50 | input p95 | output p50 | output p95 |
|---|---|---|---|---|---|
| app/extract.py:parse_invoice | 814 | 26,022 | 45,191 | 700 | 1,676 |
| app/chat.py:reply | 3,386 | 4,316 | 5,844 | 147 | 373 |
| app/summarize.py:summarise | 589 | 2,943 | 4,648 | 233 | 448 |
| app/gate.py:should_escalate | 3,035 | 688 | 1,231 | 0 | 0 |

### Five costliest tasks (ids are sha256 hashes)

| task | route | calls | cost | share of spend |
|---|---|---|---|---|
| b6f86bdea82d | app/extract.py:parse_invoice | 3 | $0.386 | 0.5% of spend |
| bb4b826d35ad | app/extract.py:parse_invoice | 2 | $0.273 | 0.3% of spend |
| 3b8e7137f839 | app/extract.py:parse_invoice | 3 | $0.271 | 0.3% of spend |
| 4c4e30b2f2cb | app/extract.py:parse_invoice | 3 | $0.269 | 0.3% of spend |
| f5cb0e514138 | app/extract.py:parse_invoice | 3 | $0.264 | 0.3% of spend |

### Latency per model

| model | calls | latency p50 | latency p95 | TTFT p50 | TTFT p95 |
|---|---|---|---|---|---|
| claude-sonnet-5-5 | 4,200 | 3,574 ms | 18,892 ms | 652 ms | 1,053 ms |
| jev-1.14.0 | 3,035 | 125 ms | 156 ms | n/a | n/a (n=0, under 200) |
| gpt-4o | 589 | 4,844 ms | 8,925 ms | n/a | n/a (n=0, under 200) |

### Per-prefix table

| prefix | route | calls | prefix tokens | calls with cached tokens | repeats inside cache TTL |
|---|---|---|---|---|---|
| 4d6292de6096 | app/gate.py:should_escalate | 3,035 | 250 | 0.0% of its calls | 55.4% of repeats (n=3,034) |
| fda4e55cbc8a | app/extract.py:parse_invoice | 814 | 6,000 | 0.0% of its calls | 98.4% of repeats (n=813) |

### Candidate-call definitions

- Routing candidate: a call on a model and route group with 200+ calls whose provider has a lower tier, with input and output tokens at or under that group's medians.
- Trimming candidate: a call that is not the first of its session on its route, in a session with 3+ calls there; excess = its input tokens minus the first call's.
- Output-cap candidate: a call above the p95 output of its model and route group (200+ calls).
- Batching candidate: a call that is not streamed (streamed column, else no TTFT) on a provider with a batch discount.
- Retry: a failed call followed by a later call in the same task on the same model.
- Cache hit (low end): a call within the provider's cache time-to-live of the previous call on the same prefix_hash and provider, with the prefix at or above the provider's minimum cacheable tokens.
