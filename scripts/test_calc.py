"""Tests for calc.py (stdlib unittest). Run: python scripts/test_calc.py"""
import json
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calc  # noqa: E402

PRICES = calc.load_prices(os.path.join(HERE, "prices.json"))


def make_rows(n_voice=400, n_chat=300, n_small=50, seed=3):
    """A small mixed export: three routes, two providers, one route under 200 calls."""
    rng = random.Random(seed)
    rows = []
    t = 1_700_000_000
    for i in range(n_voice):
        t += rng.randint(5, 40)
        sess = "v%03d" % (i // 8)
        rows.append(dict(timestamp=t, route="voice", model="claude-sonnet-4-5", input_tokens=3500 + (i % 8) * 120,
                         output_tokens=rng.randint(20, 150), cached_input_tokens=0, latency_ms=2000, ttft_ms=rng.randint(400, 1200),
                         task_id=sess, session_id=sess, success="false" if i % 37 == 0 else "true", streamed="true",
                         prefix_hash="aaa111", prefix_tokens=3200))
    for i in range(n_chat):
        t += rng.randint(5, 40)
        rows.append(dict(timestamp=t, route="chat", model="gpt-4o", input_tokens=rng.randint(1500, 6000),
                         output_tokens=rng.randint(20, 400), cached_input_tokens=0, latency_ms=3000, ttft_ms=rng.randint(300, 900),
                         task_id="c%04d" % i, session_id="c%04d" % i, success="true", streamed="true",
                         prefix_hash="bbb222", prefix_tokens=1500))
    for i in range(n_small):
        t += rng.randint(5, 40)
        rows.append(dict(timestamp=t, route="small", model="claude-sonnet-4-5", input_tokens=2000, output_tokens=100,
                         cached_input_tokens=0, latency_ms=900, ttft_ms=300, task_id="m%03d" % i, session_id="m%03d" % i,
                         success="true", streamed="true", prefix_hash="ccc333", prefix_tokens=1200))
    return rows


def run(rows, **kw):
    parsed = calc.parse_rows(rows)
    return calc.analyze(parsed, PRICES, **kw)


def one_call(**kw):
    """Cost of a single call row at the real prices."""
    row = dict(model="claude-sonnet-4-5", input_tokens=10000, output_tokens=500, timestamp=1_700_000_000)
    row.update(kw)
    ctx = run([row])
    return ctx, calc.cost(ctx.base[0])


class WaterfallTests(unittest.TestCase):
    def setUp(self):
        self.ctx = run(make_rows())

    def test_after_earlier_sums_equal_total_reduction(self):
        base = self.ctx.spend
        for level in ("low", "high"):
            summed = sum(r["after_" + level] for r in self.ctx.rows)
            self.assertAlmostEqual(summed, base - self.ctx.final[level], places=6)

    def test_standalone_is_never_below_after_for_the_same_chain_start(self):
        first = self.ctx.rows[0]
        self.assertAlmostEqual(first["alone_high"], first["after_high"], places=9)
        self.assertAlmostEqual(first["alone_low"], first["after_low"], places=9)

    def test_range_is_ordered_and_totals_add_up(self):
        for r in self.ctx.rows:
            self.assertLessEqual(r["lo"], r["hi"] + 1e-12)
        self.assertAlmostEqual(self.ctx.low_total, sum(r["lo"] for r in self.ctx.rows) * self.ctx.k, places=6)
        self.assertAlmostEqual(self.ctx.high_total, sum(r["hi"] for r in self.ctx.rows) * self.ctx.k, places=6)

    def test_spend_split_adds_to_total(self):
        agg = calc.money_table(self.ctx)
        uncached = sum(v[1] for v in agg.values())
        cached = sum(v[2] for v in agg.values())
        output = sum(v[3] for v in agg.values())
        writes = sum(v[4] for v in agg.values())
        self.assertAlmostEqual(uncached + cached + writes + output, self.ctx.spend, places=6)
        # a model's spend includes its output, so it differs from uncached-input spend
        by_model = {}
        for (m, _), v in agg.items():
            by_model[m] = by_model.get(m, 0.0) + sum(v[1:])
        self.assertAlmostEqual(sum(by_model.values()), self.ctx.spend, places=6)
        self.assertGreater(output, 0.0)


class RoutingTests(unittest.TestCase):
    def test_routing_never_crosses_providers(self):
        ctx = run(make_rows())
        self.assertTrue(ctx.route_cand)
        for i, target in ctx.route_cand.items():
            src = ctx.prices["models"][ctx.calls[i].model]
            dst = ctx.prices["models"][target]
            self.assertEqual(src["provider"], dst["provider"])
            self.assertLess(dst["tier"], src["tier"])

    def test_next_tier_down_stays_inside_provider(self):
        self.assertEqual(calc.next_tier_down(PRICES, "claude-sonnet-4-5"), "claude-haiku-4-5")
        self.assertEqual(calc.next_tier_down(PRICES, "gpt-4o"), "gpt-4o-mini")
        self.assertIsNone(calc.next_tier_down(PRICES, "gpt-4o-mini"))
        self.assertIsNone(calc.next_tier_down(PRICES, "claude-haiku-4-5"))
        self.assertIsNone(calc.next_tier_down(PRICES, "jev-1.14.0"))


class PercentileTests(unittest.TestCase):
    def test_no_p95_under_200(self):
        self.assertIn("n/a", calc.p95(list(range(199))))
        self.assertNotIn("n/a", calc.p95(list(range(200))))

    def test_small_route_gets_no_p95_in_report(self):
        ctx = run(make_rows())
        text = calc.render(ctx)
        small_group = ("claude-sonnet-4-5", "small")
        self.assertNotIn(small_group, ctx.caps)          # no output cap from 50 calls
        self.assertNotIn(small_group, ctx.route_def)     # no routing from 50 calls
        row = [l for l in text.splitlines() if l.startswith("| small |") and "TTFT" not in l and "n=50, under 200" in l]
        self.assertTrue(row, "small route should show 'n=50, under 200' instead of a p95")

    def test_no_caching_dollars_without_prefix_hash(self):
        rows = make_rows()
        for r in rows:
            r.pop("prefix_hash")
            r.pop("prefix_tokens")
        ctx = run(rows)
        self.assertNotIn("caching", [r["step"]["key"] for r in ctx.rows])
        self.assertTrue(any("prefix_hash" in why for _, why in ctx.not_estimated))


class DataQualityTests(unittest.TestCase):
    def test_dropped_rows_are_counted(self):
        rows = make_rows(n_voice=250, n_chat=0, n_small=0)
        rows.append(dict(rows[0], model=""))                             # no model
        rows.append(dict(rows[0], input_tokens="abc"))                   # not a number
        rows.append(dict(rows[0], output_tokens=-5))                     # negative
        rows.append(dict(rows[0], model="mystery-model-9"))              # kept but unpriced
        parsed = calc.parse_rows(rows)
        self.assertEqual(parsed["n_read"], len(rows))
        self.assertEqual(sum(parsed["dropped"].values()), 3)
        ctx = calc.analyze(parsed, PRICES)
        self.assertEqual(ctx.unpriced_rows, 1)
        self.assertEqual(len(ctx.calls), 250)
        text = calc.render(ctx)
        self.assertIn("%s rows read, 3 dropped, 1 on unpriced models" % format(len(rows), ","), text)
        self.assertIn("mystery-model-9", text)


class ReportShapeTests(unittest.TestCase):
    def test_first_line_states_a_dollar_result_and_sections_in_order(self):
        text = calc.render(run(make_rows()))
        self.assertTrue(text.splitlines()[0].startswith("# $"))
        pos = 0
        for marker in ["Workload view", "opportunities in detail", "Method and limits", "Next step", "## Appendix"]:
            nxt = text.find(marker, pos)
            self.assertGreater(nxt, -1, marker)
            pos = nxt

    def test_budget_line_only_when_given(self):
        rows = make_rows()
        self.assertNotIn("budget", calc.render(run(rows)).split("## ")[0])
        self.assertIn("over your 1,000 ms budget", calc.render(run(rows, ttft_budget=1000.0)))

    def test_projection_uses_window(self):
        ctx = run(make_rows())
        self.assertAlmostEqual(ctx.monthly, ctx.spend * 30.0 / ctx.days, places=6)


# ------------------------------------------------------------ D3 fixes
class ModelNormalisationTests(unittest.TestCase):
    def test_exact_match_wins_over_stripping(self):
        prices = {"models": {"x-20250514": {}, "x": {}}, "aliases": {}}
        self.assertEqual(calc.normalise_model("x-20250514", prices), "x-20250514")
        self.assertEqual(calc.normalise_model("x", prices), "x")

    def test_provider_prefix_and_date_suffix_are_stripped(self):
        n = lambda s: calc.normalise_model(s, PRICES)
        self.assertEqual(n("anthropic/claude-sonnet-4-5"), "claude-sonnet-4-5")
        self.assertEqual(n("claude-sonnet-4-5-20250514"), "claude-sonnet-4-5")
        self.assertEqual(n("anthropic/claude-haiku-4-5-20251001"), "claude-haiku-4-5")
        self.assertEqual(n("openai/gpt-4o"), "gpt-4o")
        self.assertEqual(n("gpt-4o-2024-08-06"), "gpt-4o")
        self.assertEqual(n("openai/gpt-4o-mini-2024-07-18"), "gpt-4o-mini")

    def test_unknown_models_stay_unmatched(self):
        self.assertIsNone(calc.normalise_model("mystery-model-9", PRICES))
        self.assertIsNone(calc.normalise_model("anthropic/mystery-20250514", PRICES))

    def test_normalised_rows_are_priced_and_grouped_with_the_exact_name(self):
        rows = make_rows(n_voice=250, n_chat=0, n_small=0)
        rows.append(dict(rows[0], model="anthropic/claude-sonnet-4-5-20250514"))
        ctx = run(rows)
        self.assertEqual(ctx.unpriced_rows, 0)
        self.assertEqual(len(ctx.calls), 251)
        self.assertEqual(set(c.model for c in ctx.calls), {"claude-sonnet-4-5"})


class UnpricedWarningTests(unittest.TestCase):
    def test_warning_in_headline_block_with_count_and_share(self):
        rows = make_rows(n_voice=250, n_chat=0, n_small=0)
        rows += [dict(rows[0], model="mystery-model-9") for _ in range(50)]     # 50 of 300 rows
        lines = calc.render(run(rows)).splitlines()
        self.assertTrue(lines[0].startswith("# $"))
        self.assertIn("WARNING", lines[1])
        self.assertIn("50 of 300 rows (16.7%)", lines[1])
        self.assertIn("mystery-model-9", lines[1])

    def test_no_warning_when_every_row_is_priced(self):
        text = calc.render(run(make_rows(n_voice=250, n_chat=0, n_small=0)))
        self.assertNotIn("WARNING", text)

    def test_all_rows_unpriced_is_a_clear_error(self):
        with self.assertRaises(SystemExit) as cm:
            run([dict(model="made-up-model-9", input_tokens=10, output_tokens=5)])
        self.assertIn("made-up-model-9", str(cm.exception))


class HashedIdTests(unittest.TestCase):
    def test_raw_task_and_session_ids_never_appear(self):
        rows = make_rows(n_voice=250, n_chat=0, n_small=0)
        rows.append(dict(rows[0], task_id="secret-customer-4711", session_id="secret-session-4711",
                         input_tokens=900000, output_tokens=90000))
        text = calc.render(run(rows))
        self.assertNotIn("secret-customer-4711", text)
        self.assertNotIn("secret-session-4711", text)
        # the costliest task is listed, by its short hash
        h = calc.hid("secret-customer-4711")
        self.assertEqual(len(h), 10)
        self.assertRegex(h, r"^[0-9a-f]{10}$")
        self.assertIn(h, text)

    def test_hashing_keeps_task_grouping(self):
        ctx = run(make_rows(n_voice=16, n_chat=0, n_small=0))
        self.assertEqual(len(ctx.tasks), 2)        # v000 and v001, 8 calls each
        self.assertEqual(sorted(len(v) for v in ctx.tasks.values()), [8, 8])


class CacheWriteTests(unittest.TestCase):
    def test_one_hour_writes_cost_twice_input_and_five_minute_writes_keep_the_provider_multiplier(self):
        # 10000 input = 4000 uncached + 2000 cache read + 1000 5m write + 3000 1h write; 500 output; sonnet 4.5
        ctx, c = one_call(cached_input_tokens=2000, cache_write_tokens=1000, cache_write_1h_tokens=3000)
        expect = (4000 * 3.00 + 2000 * 0.30 + 1000 * 3.00 * 1.25 + 3000 * 3.00 * 2.0 + 500 * 15.00) / 1e6
        self.assertAlmostEqual(c, expect, places=12)

    def test_alias_column_ephemeral_1h(self):
        _, c = one_call(ephemeral_1h_input_tokens=3000)
        _, c2 = one_call(cache_write_1h_tokens=3000)
        self.assertAlmostEqual(c, c2, places=12)
        _, plain = one_call()
        self.assertGreater(c, plain)               # 2x input is dearer than 1x input

    def test_input_excludes_cached_flag_counts_writes_too(self):
        row = dict(model="claude-sonnet-4-5", input_tokens=4000, output_tokens=500, cached_input_tokens=2000,
                   cache_write_tokens=1000, cache_write_1h_tokens=3000, timestamp=1_700_000_000)
        ctx = calc.analyze(calc.parse_rows([row], input_excludes_cached=True), PRICES)
        _, inclusive = one_call(cached_input_tokens=2000, cache_write_tokens=1000, cache_write_1h_tokens=3000)
        self.assertAlmostEqual(calc.cost(ctx.base[0]), inclusive, places=12)

    def test_split_adds_to_total_with_writes_present(self):
        rows = make_rows()
        for i, r in enumerate(rows):
            if r["model"] == "claude-sonnet-4-5" and i % 5 == 0:
                r["cache_write_tokens"] = 800
                r["cache_write_1h_tokens"] = 1000
                r["cached_input_tokens"] = 600
        ctx = run(rows)
        agg = calc.money_table(ctx)
        self.assertGreater(sum(v[4] for v in agg.values()), 0.0)
        self.assertAlmostEqual(sum(sum(v[1:]) for v in agg.values()), ctx.spend, places=6)
        text = calc.render(ctx)                    # routing/caching/trimming steps run on rows with writes
        self.assertIn("cache writes", text)
        for level in ("low", "high"):
            summed = sum(r["after_" + level] for r in ctx.rows)
            self.assertAlmostEqual(summed, ctx.spend - ctx.final[level], places=6)

    def test_writes_cannot_exceed_input(self):
        ctx, _ = one_call(input_tokens=1000, cached_input_tokens=400, cache_write_tokens=900, cache_write_1h_tokens=900)
        s = ctx.base[0]
        self.assertAlmostEqual(s.u + s.c + s.cw + s.cw1, 1000.0)
        self.assertGreaterEqual(s.u, 0.0)


class JevPriceTests(unittest.TestCase):
    def test_jev_priced_row(self):
        m = PRICES["models"]["jev-1.14.0"]
        self.assertEqual(m["provider"], "typesafe")
        self.assertEqual(m["input"], 0.042)
        self.assertEqual(m["output"], 0.0)

    def test_jev_names_normalise(self):
        for name in ("jev-1.14.0", "jev-latest", "jev", "Jev"):
            self.assertEqual(calc.normalise_model(name, PRICES), "jev-1.14.0", name)

    def test_jev_cost_is_input_only(self):
        _, c = one_call(model="jev-latest", input_tokens=1_000_000, output_tokens=5000)
        self.assertAlmostEqual(c, 0.042, places=9)

    def test_jev_adds_no_savings_ideas(self):
        rows = [dict(timestamp=1_700_000_000 + i * 10, route="gate", model="jev", input_tokens=2000, output_tokens=10,
                     task_id="g%d" % i, prefix_hash="jjj", prefix_tokens=1500) for i in range(300)]
        ctx = run(rows)
        self.assertEqual(ctx.unpriced_rows, 0)
        self.assertAlmostEqual(ctx.spend, 300 * 2000 * 0.042 / 1e6, places=9)
        self.assertAlmostEqual(ctx.high_total, 0.0, places=9)


class InputFormatTests(unittest.TestCase):
    def test_jsonl_with_ttft_and_route_columns(self):
        rows = [dict(timestamp=1_700_000_000 + i, route="voice:answer", model="claude-sonnet-4-5", input_tokens=2000,
                     output_tokens=50, ttft_ms=400 + i) for i in range(10)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rows.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            raw, bad = calc.read_raw(p)
            self.assertEqual((len(raw), bad), (10, 0))
            ctx = calc.analyze(calc.parse_rows(raw, bad), PRICES)
            self.assertTrue(ctx.has["ttft"])
            self.assertTrue(ctx.has["route"])
            self.assertEqual(set(c.route for c in ctx.calls), {"voice:answer"})
            self.assertEqual(sorted(c.ttft for c in ctx.calls)[0], 400.0)
            out = os.path.join(d, "report.md")
            calc.main([p, "-o", out])
            with open(out, encoding="utf-8") as f:
                self.assertTrue(f.readline().startswith("# $"))


def cache_rows(n_sessions=4, per_session=5, stateless=False, with_session=True):
    """One route on claude-sonnet-4-5, no prefix_hash. Every call reads 500 cached tokens; calls 0 and 2 of a
    session write 3000 tokens at the 1-hour rate; calls 1 and 3 write 1000 tokens at the 5-minute rate."""
    rows, t = [], 1_700_000_000
    for s in range(n_sessions):
        for k in range(per_session):
            t += 30
            r = dict(timestamp=t, route="app.py:Writer.run", model="claude-sonnet-4-5", input_tokens=5000, output_tokens=100,
                     cached_input_tokens=500)
            if k in (0, 2):
                r["cache_write_1h_tokens"] = 3000
            if k in (1, 3):
                r["cache_write_tokens"] = 1000
            if with_session:
                r["session_id"] = "w%d" % s
            if stateless:
                r["stateless"] = True
            rows.append(r)
    return rows


class CacheInUseTests(unittest.TestCase):
    def setUp(self):
        self.rows = cache_rows()
        self.ctx = run(self.rows)
        self.text = calc.render(self.ctx)

    def test_measured_dollars_without_prefix_hash(self):
        self.assertNotIn("prefix_hash", self.rows[0])
        (g,) = self.ctx.cache["rows"]
        n = 20
        self.assertAlmostEqual(g["read"], n * 500 * 0.30 / 1e6, places=12)
        self.assertAlmostEqual(g["w1"], 8 * 3000 * 3.00 * 2.0 / 1e6, places=12)       # calls 0 and 2, four sessions
        self.assertAlmostEqual(g["w5"], 8 * 1000 * 3.00 * 1.25 / 1e6, places=12)      # calls 1 and 3, four sessions
        self.assertEqual(calc.cache_ratio(g["w1"] + g["w5"], g["read"]), "%.0fx" % ((g["w1"] + g["w5"]) / g["read"]))

    def test_cache_totals_stay_inside_the_spend_invariant(self):
        agg = calc.money_table(self.ctx)
        uncached, cached, output, writes = (sum(v[i] for v in agg.values()) for i in (1, 2, 3, 4))
        self.assertAlmostEqual(uncached + cached + writes + output, self.ctx.spend, places=9)
        t = self.ctx.cache["tot"]
        self.assertAlmostEqual(t["read"], cached, places=12)
        self.assertAlmostEqual(t["w5"] + t["w1"], writes, places=12)

    def test_rewrites_after_the_first_call_of_a_session(self):
        t = self.ctx.cache["tot"]
        self.assertEqual((t["later"], t["rewr"]), (16, 12))        # per session: calls 1, 2, 3 write; call 4 does not
        (g,) = self.ctx.cache["rows"]
        self.assertAlmostEqual(g["rewr_usd"], 4 * (3000 * 6.00 + 2 * 1000 * 3.75) / 1e6, places=12)
        self.assertIn("12 of 16 later calls", self.text)

    def test_rewrites_not_counted_without_session_id_or_when_stateless(self):
        for rows, word in ((cache_rows(with_session=False), "no session_id"), (cache_rows(stateless=True), "stateless")):
            ctx = run(rows)
            self.assertEqual(ctx.cache["tot"]["rewr"], 0)
            self.assertIn("n/a (%s" % word, calc.render(ctx))

    def test_section_is_labelled_measured_and_has_no_savings_dollar(self):
        sec = calc.cache_section(self.ctx)
        self.assertTrue(sec[0].startswith("## Cache in use (MEASURED)"))
        self.assertIn("carries no savings dollar", "\n".join(sec))
        self.assertNotIn("caching", [r["step"]["key"] for r in self.ctx.rows])    # no prefix_hash, no mechanism

    def test_headline_leads_with_the_measured_fact_when_savings_are_zero(self):
        self.assertAlmostEqual(self.ctx.a_high, 0.0, places=9)
        lines = self.text.splitlines()
        t = self.ctx.cache["tot"]
        self.assertTrue(lines[0].startswith("# %s of spend is cache writes" % calc.share(t["writes"], self.ctx.spend, 0)), lines[0])
        self.assertIn("x cache reads (MEASURED)", lines[0])
        self.assertIn("savings that do not change model output: $0", lines[0])
        # the savings line stays in the body
        self.assertTrue(any(l.startswith("- **Savings that do not change model output:**") for l in lines))

    def test_do_first_points_at_the_cache_route_when_nothing_else_clears_zero(self):
        self.assertAlmostEqual(self.ctx.a_high, 0.0, places=9)    # only an unproven (HYPOTHESIS) idea, batching, is ranked
        do_first = [l for l in self.text.splitlines() if l.startswith("- **Do first:**")][0]
        self.assertIn("cut cache re-writes on app.py:Writer.run", do_first)
        self.assertIn("MEASURED", do_first)
        self.assertIn("No savings dollar", do_first)
        self.assertIn("Largest unproven idea after that", do_first)
        self.assertIn("pilot on app.py:Writer.run", self.text)

    def test_headline_is_unchanged_when_savings_exist(self):
        ctx = run(make_rows())
        self.assertTrue(calc.render(ctx).splitlines()[0].startswith("# $"))
        self.assertFalse(ctx.cache_lead)

    def test_small_cache_write_share_does_not_lead(self):
        rows = cache_rows()
        for r in rows:
            r.pop("cache_write_1h_tokens", None)
            r["cache_write_tokens"] = 20            # a few dollars-of-nothing in writes
            r["output_tokens"] = 4000
        ctx = run(rows)
        self.assertFalse(ctx.cache_lead)
        self.assertTrue(calc.render(ctx).splitlines()[0].startswith("# $"))

    def test_section_says_so_when_there_is_no_cache_data(self):
        text = calc.render(run(make_rows(n_voice=250, n_chat=0, n_small=0)))
        self.assertIn("## Cache in use (MEASURED): none seen", text)

    def test_prefix_hash_path_is_kept(self):
        rows = make_rows()
        self.assertIn("caching", [r["step"]["key"] for r in run(rows).rows])


class LeadFactAndCacheChurnTests(unittest.TestCase):
    def test_headline_leads_with_the_fact_when_savings_are_under_one_percent(self):
        ctx = run(cache_rows())
        for share_, leads in ((0.005, True), (0.02, False)):
            ctx.a_low = ctx.a_high = share_ * ctx.monthly
            first = calc.render(ctx).splitlines()[0]
            self.assertEqual(first.startswith("# $"), not leads, first)
            if leads:
                self.assertIn("of spend is cache writes", first)
                self.assertIn("(MEASURED); savings that do not change model output: $", first)

    def test_route_that_already_caches_gets_the_rewrite_finding_not_the_caching_action(self):
        rows = cache_rows()
        for r in rows:
            r["prefix_hash"], r["prefix_tokens"] = "pp1", 3000
        ctx = run(rows)
        self.assertIn("app.py:Writer.run", ctx.cached_routes)
        self.assertNotIn("caching", [r["step"]["key"] for r in ctx.ranked])
        text = calc.render(ctx)
        self.assertNotIn("Turn on prompt caching |", text)
        self.assertIn("Checked, nothing to save: turn on prompt caching", text)
        (f,) = ctx.rewrite_findings
        self.assertEqual(f["rewr"], 12)
        self.assertAlmostEqual(f["usd"], 4 * (3000 * 6.00 + 2 * 1000 * 3.75) / 1e6, places=12)
        self.assertIn("## Measured findings with no savings dollar", text)
        self.assertIn("| Cut cache re-writes | app.py:Writer.run | 12 of 16 later calls", text)
        do_first = [l for l in text.splitlines() if l.startswith("- **Do first:**")][0]
        self.assertTrue(do_first.startswith("- **Do first:** cut cache re-writes on app.py:Writer.run (MEASURED: 12 re-writes"), do_first)
        self.assertIn("No savings dollar", do_first)

    def test_route_that_does_not_cache_still_gets_the_caching_action_and_no_finding(self):
        ctx = run(make_rows())
        self.assertEqual(ctx.cached_routes, set())
        self.assertEqual(ctx.rewrite_findings, [])
        self.assertIn("caching", [r["step"]["key"] for r in ctx.ranked])
        self.assertNotIn("Measured findings with no savings dollar", calc.render(ctx))

    def test_below_half_of_calls_caching_is_still_offered(self):
        rows = make_rows()
        for i, r in enumerate(rows):
            if r["route"] == "voice" and i % 3 == 0:
                r["cached_input_tokens"] = 100          # one in three voice calls reads the cache
        ctx = run(rows)
        self.assertNotIn("voice", ctx.cached_routes)
        self.assertIn("caching", [r["step"]["key"] for r in ctx.ranked])

    def test_no_finding_without_rewrites_after_the_first_call(self):
        ctx = run(cache_rows(with_session=False))
        self.assertIn("app.py:Writer.run", ctx.cached_routes)
        self.assertEqual(ctx.rewrite_findings, [])
        do_first = [l for l in calc.render(ctx).splitlines() if l.startswith("- **Do first:**")][0]
        self.assertIn("app.py:Writer.run writes the cache", do_first)


class UsageMissingTests(unittest.TestCase):
    def rows(self):
        rows = make_rows(n_voice=250, n_chat=0, n_small=0)
        rows += [dict(timestamp=1_700_000_000 + i, route="state.py:memo", model="claude-haiku-4-5", usage_missing=True, latency_ms=900)
                 for i in range(28)]
        rows += [dict(timestamp=1_700_000_000 + i, route="layout.py:fit", usage_missing="true") for i in range(2)]   # no model
        return rows

    def test_rows_are_counted_per_route_and_excluded_from_spend(self):
        base = run(make_rows(n_voice=250, n_chat=0, n_small=0))
        ctx = run(self.rows())
        self.assertEqual(len(ctx.usage_missing), 30)
        self.assertEqual(dict(ctx.um_by_route), {"state.py:memo": 28, "layout.py:fit": 2})
        self.assertAlmostEqual(ctx.spend, base.spend, places=12)
        self.assertEqual(len(ctx.calls), 250)
        self.assertEqual(sum(ctx.dropped.values()), 0)         # flagged rows are not "dropped"

    def test_headline_area_says_spend_is_a_floor(self):
        lines = calc.render(run(self.rows())).splitlines()
        self.assertTrue(lines[0].startswith("# $"))
        self.assertIn("Spend is a floor: 30 calls on 2 routes have no token usage logged", lines[1])

    def test_no_floor_line_when_every_row_has_usage(self):
        self.assertNotIn("Spend is a floor", calc.render(run(make_rows(n_voice=250, n_chat=0, n_small=0))))

    def test_report_lists_the_routes_and_the_data_line_counts_them(self):
        text = calc.render(run(self.rows()))
        self.assertIn("## Calls with no token usage logged", text)
        self.assertRegex(text, r"\| state\.py:memo \| 28 \| claude-haiku-4-5 \|")
        self.assertIn("30 flagged usage_missing", text)

    def test_token_columns_may_be_absent_when_every_row_is_flagged_but_nothing_can_be_priced(self):
        with self.assertRaises(SystemExit) as cm:
            run([dict(route="a", model="claude-sonnet-4-5", usage_missing=True)])
        self.assertIn("usage_missing", str(cm.exception))

    def test_token_columns_still_required_for_unflagged_rows(self):
        with self.assertRaises(SystemExit) as cm:
            calc.parse_rows([dict(model="claude-sonnet-4-5", usage_missing=True), dict(model="claude-sonnet-4-5")])
        self.assertIn("missing required column", str(cm.exception))

    def test_flagged_rows_first_in_the_file_do_not_hide_token_columns(self):
        rows = [dict(model="claude-sonnet-4-5", route="warm", usage_missing=True) for _ in range(60)]
        rows.append(dict(model="claude-sonnet-4-5", route="live", input_tokens=100, output_tokens=10))
        ctx = run(rows)
        self.assertEqual((len(ctx.calls), len(ctx.usage_missing)), (1, 60))


class StatelessTests(unittest.TestCase):
    def rows(self, stateless):
        rows = []
        for i in range(30):                      # per-utterance gate: input grows 100 tokens per call, one shared session id
            rows.append(dict(timestamp=1_700_000_000 + i * 10, route="gate.py:judge", model="claude-sonnet-4-5",
                             input_tokens=2000 + i * 100, output_tokens=10, session_id="meeting-1", stateless=stateless))
        return rows

    def test_trimming_is_skipped_for_stateless_routes(self):
        self.assertTrue(run(self.rows(False)).excess)
        ctx = run(self.rows(True))
        self.assertFalse(ctx.excess)
        self.assertTrue(any("trim" in n.lower() for n, _ in ctx.not_estimated))
        self.assertNotIn("trimming", [r["step"]["key"] for r in ctx.rows])

    def test_mixed_routes_only_the_stateless_one_is_skipped(self):
        rows = self.rows(True) + [dict(timestamp=1_700_001_000 + i * 10, route="chat.py:reply", model="claude-sonnet-4-5",
                                       input_tokens=2000 + i * 100, output_tokens=10, session_id="chat-1") for i in range(10)]
        ctx = run(rows)
        self.assertEqual(set(ctx.calls[i].route for i in ctx.excess), {"chat.py:reply"})

    def test_stateless_column_is_documented_in_method_and_read_from_strings(self):
        rows = self.rows("true")
        self.assertTrue(all(c.stateless for c in run(rows).calls))
        self.assertIn("Stateless routes", calc.render(run(rows)))


class LoggedCostTests(unittest.TestCase):
    def test_reconciliation_line_and_cumulative_warning(self):
        rows, running = [], 0.0
        for i in range(12):                       # a running total per process, not a per-call cost
            running += 0.01
            rows.append(dict(timestamp=1_700_000_000 + i * 10, route="w.py:run", model="claude-sonnet-4-5", input_tokens=1000,
                             output_tokens=50, logged_cost_usd=running))
        ctx = run(rows)
        line = calc.logged_cost_line(ctx)
        self.assertIn("logged_cost_usd sums to $0.78", line)
        self.assertIn("price at", line)
        self.assertIn("may be cumulative", line)
        self.assertIn("looks cumulative", line)
        self.assertIn("**Logged cost check:**", calc.render(ctx))

    def test_per_call_costs_do_not_look_cumulative(self):
        rows = [dict(timestamp=1_700_000_000 + i * 10, route="w.py:run", model="claude-sonnet-4-5", input_tokens=1000,
                     output_tokens=50, logged_cost_usd=0.005 + 0.003 * ((i * 7) % 5)) for i in range(12)]
        self.assertNotIn("looks cumulative", calc.logged_cost_line(run(rows)))

    def test_no_line_without_the_column(self):
        self.assertIsNone(calc.logged_cost_line(run(make_rows(n_voice=250, n_chat=0, n_small=0))))


class ScanOnlyTests(unittest.TestCase):
    DOC = dict(routes=[dict(id="a.py:live_route", kind="sdk", live=True),
                       dict(id="warm.py:keepalive", kind="cli", live=True),
                       dict(id="mystery.py:maybe", kind="http", live="unknown"),
                       dict(id="t.py:test_only", kind="sdk", live=False),
                       dict(id="stt.py:transcribe", kind="non_llm", live=True)],
               usage_gaps=["warm-up calls seen 40 times in the logs carry no usage"])

    def render(self, doc):
        rows = [dict(timestamp=1_700_000_000 + i, route="a.py:live_route", model="claude-sonnet-4-5", input_tokens=500, output_tokens=20)
                for i in range(5)]
        rows += [dict(timestamp=1_700_000_000 + i, route="warm.py:keepalive", model="claude-haiku-4-5", usage_missing=True) for i in range(40)]
        ctx = run(rows)
        ctx.routes_doc = doc
        return calc.render(ctx)

    def test_section_lists_gaps_and_routes_with_no_rows_without_dollars(self):
        text = self.render(self.DOC)
        sec = text[text.index("## Scan-only findings"):]
        sec = sec[:sec.index("## Method")]
        self.assertIn("(UNMEASURED, no dollars)", sec)
        self.assertIn("Usage gap: warm-up calls seen 40 times in the logs carry no usage", sec)
        self.assertIn("warm.py:keepalive (live: yes): no priced rows in the export; 40 calls were seen with no token usage logged", sec)
        self.assertIn("mystery.py:maybe (live: unknown): no priced rows", sec)
        self.assertIn("1 test-only route with no rows (not live): t.py:test_only", sec)
        self.assertIn("Out of scope (not LLM calls, kind non_llm): stt.py:transcribe", sec)
        self.assertNotIn("a.py:live_route", sec)               # it has priced rows
        self.assertNotIn("$", sec)

    def test_no_section_without_routes_file(self):
        self.assertNotIn("Scan-only", calc.render(run(make_rows(n_voice=250, n_chat=0, n_small=0))))

    def test_routes_option_on_the_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            rp, cp, out = (os.path.join(d, n) for n in ("routes.json", "rows.jsonl", "report.md"))
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(self.DOC, f)
            with open(cp, "w", encoding="utf-8") as f:
                f.write(json.dumps(dict(model="claude-sonnet-4-5", route="a.py:live_route", input_tokens=10, output_tokens=5)) + "\n")
            calc.main([cp, "--routes", rp, "-o", out])
            with open(out, encoding="utf-8") as f:
                self.assertIn("## Scan-only findings (UNMEASURED, no dollars)", f.read())


class StructuralHashTests(unittest.TestCase):
    def test_structural_prefix_hash_is_disclosed(self):
        rows = make_rows()
        for r in rows:
            r["prefix_hash_kind"] = "structural"
        ctx = run(rows)
        self.assertEqual(ctx.struct_hash_rows, len(rows))
        text = calc.render(ctx)
        self.assertIn("structural prefix_hash (route, model and process generation)", text)
        self.assertEqual(run(make_rows()).struct_hash_rows, 0)


class CheckRowsNewColumnTests(unittest.TestCase):
    def test_new_columns_and_usage_missing_rows(self):
        import check_rows
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rows.jsonl")

            def check(*rows):
                with open(p, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")
                return check_rows.check_rows(p)

            ok = dict(model="m", input_tokens=1, output_tokens=0, stateless=True, prefix_hash_kind="structural", logged_cost_usd=0.01)
            self.assertEqual(check(ok, dict(model="m", route="a.py:f", usage_missing=True, latency_ms=900, timestamp=1)), [])
            self.assertEqual(check(dict(route="a.py:f", usage_missing=True)), [])
            self.assertTrue(any("carries token counts" in x for x in check(dict(model="m", usage_missing=True, input_tokens=5))))
            self.assertTrue(any("required unless usage_missing" in x for x in check(dict(model="m", input_tokens=5))))
            self.assertTrue(any("prefix_hash_kind" in x for x in check(dict(ok, prefix_hash_kind="guess"))))
            self.assertTrue(any("must be true or false" in x for x in check(dict(ok, stateless="maybe"))))


class PrivacyCheckTests(unittest.TestCase):
    def test_hits_are_reported_without_the_phrase_or_its_context(self):
        import io
        import contextlib
        import privacy_check
        phrase = "the quarterly budget slips again"
        with tempfile.TemporaryDirectory() as d:
            work = os.path.join(d, "work")
            os.makedirs(work)
            with open(os.path.join(work, "report.md"), "w", encoding="utf-8") as f:
                f.write("# report\nclean numbers only\n")
            with open(os.path.join(work, "rows.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps(dict(route="x", note="He said: The  Quarterly\nBUDGET slips again, then left")) + "\n")
            pf = os.path.join(d, "phrases.txt")
            with open(pf, "w", encoding="utf-8") as f:
                f.write(phrase + "\n\nnot present anywhere in these files\nab\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = privacy_check.main([work, "--phrases-file", pf])
            out = buf.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("rows.jsonl", out)
            self.assertIn("phrases.txt line 1 (5 words)", out)
            self.assertIn("1 hits", out)
            self.assertIn("1 skipped", out)
            for fragment in ("quarterly", "budget", "slips", "then left"):
                self.assertNotIn(fragment, out.lower())

    def test_clean_run_and_phrases_file_inside_the_searched_folder_is_ignored(self):
        import io
        import contextlib
        import privacy_check
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "report.md"), "w", encoding="utf-8") as f:
                f.write("totals only")
            pf = os.path.join(d, "phrases.txt")                  # inside the folder being searched
            with open(pf, "w", encoding="utf-8") as f:
                f.write("secret customer sentence\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(privacy_check.main([d, "--phrases-file", pf]), 0)

    def test_json_escaped_phrase_is_found(self):
        import privacy_check
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "rows.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps(dict(v='she said "hello there friend"')) + "\n")
            pf = os.path.join(d, "..", os.path.basename(d) + "_p.txt")
            with open(pf, "w", encoding="utf-8") as f:
                f.write('said "hello there friend"\n')
            try:
                hits, n, _, _ = privacy_check.find_hits([d], [pf])
            finally:
                os.remove(pf)
            self.assertEqual((n, len(hits)), (1, 1))


class CheckRowsTests(unittest.TestCase):
    def _write(self, d, rows):
        p = os.path.join(d, "rows.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return p

    def test_clean_rows_pass_and_text_leaks_fail(self):
        import check_rows
        good = dict(model="claude-sonnet-4-5", input_tokens=10, output_tokens=5, route="a.py:f", task_id=calc.hid("x"))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(check_rows.check_rows(self._write(d, [good])), [])
            bad_col = check_rows.check_rows(self._write(d, [dict(good, prompt="hello there")]))
            self.assertTrue(any("not in the schema" in p for p in bad_col))
            bad_text = check_rows.check_rows(self._write(d, [dict(good, route="please summarise my meeting notes")]))
            self.assertTrue(any("whitespace" in p for p in bad_text))
            p = self._write(d, [good])
            self.assertEqual(check_rows.main([p, "--forbid", "zzz-not-there"]), 0)
            self.assertEqual(check_rows.main([p, "--forbid", "a.py:f"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
