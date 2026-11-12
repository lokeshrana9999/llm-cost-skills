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
        # two models share tier 1 at anthropic: the lower input price wins
        self.assertEqual(calc.next_tier_down(PRICES, "claude-sonnet-4-5"), "claude-haiku-5-5")
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
        self.assertEqual(len(h), 12)
        self.assertRegex(h, r"^[0-9a-f]{12}$")
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


class ReviewFixTests(unittest.TestCase):
    def _prices(self):
        import copy
        return copy.deepcopy(PRICES)

    def test_tier_tie_picks_the_lowest_input_price_whatever_the_file_order(self):
        for reverse in (False, True):
            p = self._prices()
            for name, price_in in (("tie-a", 0.5), ("tie-b", 0.2), ("tie-c", 0.2)):
                p["models"][name] = dict(provider="anthropic", tier=1, input=price_in, output=1.0, cached=0.02)
            p["models"] = dict(sorted(p["models"].items(), reverse=reverse))
            # claude-haiku-5-5 (0.10) is also tier 1 and cheaper than every tie-* model
            self.assertEqual(calc.next_tier_down(p, "claude-sonnet-4-5"), "claude-haiku-5-5")
            del p["models"]["claude-haiku-5-5"]
            del p["models"]["claude-haiku-4-5"]
            self.assertEqual(calc.next_tier_down(p, "claude-sonnet-4-5"), "tie-b")     # tie-b and tie-c cost the same; the name breaks it

    def test_tie_rule_is_in_the_method_section(self):
        text = calc.render(run(make_rows()))
        self.assertIn("lowest input price", text)

    def test_implicit_cache_provider_gets_no_caching_action(self):
        ctx = run(make_rows())
        self.assertEqual(ctx.prices["providers"]["openai"].get("cache_mode"), "implicit")
        self.assertEqual(ctx.implicit_routes, {"chat"})                 # the gpt-4o route
        for key in ctx.cache_groups:
            self.assertNotEqual(key[1], "openai")
        text = calc.render(ctx)
        self.assertIn("Skipped (the provider caches automatically", text)
        for l in text.splitlines():
            if l.startswith("| 1 |") or l.startswith("- **Do first:**"):
                self.assertNotIn("app.py:chat", l)

    def test_only_implicit_routes_means_no_caching_action_at_all(self):
        rows = [r for r in make_rows() if r["route"] == "chat"]
        ctx = run(rows)
        self.assertNotIn("caching", [r["step"]["key"] for r in ctx.rows])
        self.assertTrue(any("caches these prompts automatically" in why for _, why in ctx.not_estimated))

    def test_caching_card_and_table_agree_that_no_replay_is_needed(self):
        text = calc.render(run(make_rows()))
        self.assertIn("no: compare billed cached tokens", text)
        self.assertIn("No replay is needed: caching does not change model output.", text)
        self.assertNotIn("to confirm outputs are unchanged", text)

    def test_plurals_and_ranges(self):
        self.assertEqual(calc.pl(1, "route"), "1 route")
        self.assertEqual(calc.pl(2, "route"), "2 routes")
        self.assertEqual(calc.span(1053.2, 1052.8, calc.num), "1,053")
        self.assertEqual(calc.span(900, 1053, calc.num), "900-1,053")
        self.assertEqual(calc.usd(0.00001), "<$0.0001")
        self.assertEqual(calc.usd(0), "$0.00")
        self.assertEqual(calc.price(0.075), "$0.075")
        self.assertEqual(calc.price(3.0), "$3.00")
        self.assertEqual(calc.price(0.042), "$0.042")
        self.assertEqual(calc.dur_cell([0.0, 0.0]), "n/a")

    def test_generated_text_never_says_one_plural(self):
        import re
        bad = re.compile(r"(?<![\d.=,])1 (calls|actions|opportunities|rows|routes|sessions|tasks|prefixes|repeat calls|groups)\b")
        cases = [simple_rows(1), simple_rows(1) + [dict(model="claude-sonnet-4-5", route="warm", usage_missing="true")],
                 simple_rows(3, model="gpt-4o"), simple_rows(2, success="false")]
        for scope in ("stay", "open"):
            for rows in cases:
                text = calc.render(run(rows, scope=scope))
                self.assertIsNone(bad.search(text), bad.search(text) and text[bad.search(text).start() - 40:bad.search(text).end() + 40])

    def test_one_action_and_one_opportunity_are_singular(self):
        ctx = run(simple_rows(40))                      # only batching clears $0
        self.assertEqual(len(ctx.ranked), 1)
        text = calc.render(ctx)
        self.assertIn("## 1 action is worth", text)
        self.assertIn("## The 1 opportunity in detail", text)
        text = calc.render(run(simple_rows(40, success="false")))
        self.assertIn("## 2 actions are worth", text)
        self.assertIn("## The 2 opportunities in detail", text)
        self.assertEqual(calc.pl(1, "opportunity", "opportunities"), "1 opportunity")

    def test_floor_line_says_1_route_and_1_call(self):
        rows = [dict(r) for r in make_rows(n_voice=250, n_chat=0, n_small=0)]
        rows.append(dict(model="claude-sonnet-4-5", route="warm", usage_missing="true"))
        text = calc.render(run(rows))
        self.assertIn("1 call on 1 route has no token usage logged", text)

    def test_next_step_asks_to_collect_and_rerun_not_to_share(self):
        text = calc.render(run(make_rows()))
        self.assertIn("Collect an export of 7-30 days", text)
        self.assertNotIn("Share an export", text)


# ---------------------------------------------------------------- provider scope, tool schemas, spirals, evidence
def simple_rows(n, route="r", model="claude-sonnet-4-5", inp=1000, out=100, **extra):
    """n identical calls, one task and one session each unless overridden."""
    rows = []
    for i in range(n):
        row = dict(timestamp=1_700_000_000 + i * 60, route=route, model=model, input_tokens=inp, output_tokens=out,
                   task_id="%s-t%03d" % (route, i), session_id="%s-s%03d" % (route, i), success="true")
        row.update(extra)
        rows.append(row)
    return rows


def line1(text):
    return text.splitlines()[0]


def section(text, title):
    """The report text from `## title...` up to the next `## `."""
    start = text.index("## " + title)
    end = text.find("\n## ", start + 3)
    return text[start:end if end > 0 else len(text)]


def action_table(text):
    return section(text, "6 actions") if "## 6 actions" in text else text[text.index("| rank"):text.index("Ranked by")]


class PriceClassTests(unittest.TestCase):
    def test_every_model_has_a_valid_class_and_keeps_its_tier(self):
        for name, m in PRICES["models"].items():
            self.assertIn(m.get("class"), ("decision", "small", "mid", "frontier"), name)
        self.assertEqual(PRICES["models"]["claude-sonnet-5-5"]["tier"], 2)
        self.assertEqual(PRICES["models"]["jev-1.14.0"]["class"], "decision")

    def test_every_price_row_added_for_open_scope_cites_a_url(self):
        for name in ("gpt-5-mini", "gpt-5-nano", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-decision-1"):
            self.assertIn("https://", PRICES["models"][name]["_verify"], name)
        self.assertIn("https://", PRICES["providers"]["google"]["_verify"])

    def test_every_model_and_provider_cites_a_public_pricing_url_and_a_read_date(self):
        sources = [("model " + n, m["_verify"]) for n, m in PRICES["models"].items()]
        sources += [("provider " + n, p["_verify"]) for n, p in PRICES["providers"].items()]
        for what, v in sources:
            self.assertRegex(v, r"https://\S+", what)
            self.assertRegex(v, r"(read|checked) \d{4}-\d{2}-\d{2}", what)
        self.assertIn("platform.claude.com/docs/en/about-claude/pricing", PRICES["providers"]["anthropic"]["_verify"])
        self.assertIn("developers.openai.com/api/docs/pricing", PRICES["providers"]["openai"]["_verify"])

    def test_new_rows_do_not_change_same_provider_routing(self):
        self.assertEqual(calc.next_tier_down(PRICES, "gpt-4o"), "gpt-4o-mini")
        self.assertIsNone(calc.next_tier_down(PRICES, "gpt-5-nano"))


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.rows = make_rows()
        self.stay = calc.render(run(self.rows))
        self.open = calc.render(run(self.rows, scope="open"))

    def test_default_scope_is_stay_and_header_says_so(self):
        self.assertIn("**Scope: stay.**", self.stay)
        self.assertIn("a smaller model at the same provider", self.stay)
        self.assertNotIn("Other providers (open scope", self.stay)

    def test_open_scope_header_and_section(self):
        self.assertIn("**Scope: open.**", self.open)
        self.assertIn("## Other providers (open scope, HYPOTHESIS)", self.open)

    def test_headline_and_action_table_are_scope_independent(self):
        self.assertEqual(line1(self.stay), line1(self.open))
        self.assertEqual(action_table(self.stay), action_table(self.open))
        a, b = run(self.rows), run(self.rows, scope="open")
        self.assertEqual((a.low_total, a.high_total, a.a_low, a.a_high, a.b_high), (b.low_total, b.high_total, b.a_low, b.a_high, b.b_high))

    def test_cli_default_and_choices(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "rows.jsonl")
            with open(src, "w", encoding="utf-8") as f:
                for r in simple_rows(5):
                    f.write(json.dumps(r) + "\n")
            out = os.path.join(d, "r.md")
            calc.main([src, "-o", out])
            with open(out, encoding="utf-8") as f:
                self.assertIn("**Scope: stay.**", f.read())
            calc.main([src, "-o", out, "--scope", "open"])
            with open(out, encoding="utf-8") as f:
                self.assertIn("**Scope: open.**", f.read())
            with self.assertRaises(SystemExit):
                calc.main([src, "-o", out, "--scope", "elsewhere"])

    def test_spend_split_still_adds_to_total_in_open_scope(self):
        ctx = run(self.rows, scope="open")
        agg = calc.money_table(ctx)
        self.assertAlmostEqual(sum(sum(v[1:]) for v in agg.values()), ctx.spend, places=6)


class OpenCandidateTests(unittest.TestCase):
    def cands(self, rows, routes_doc=None, prices=None):
        ctx = calc.analyze(calc.parse_rows(rows), prices or PRICES, scope="open")
        if routes_doc:
            ctx.routes_doc = routes_doc
        return ctx, dict((r["route"], r) for r in calc.open_candidates(ctx))

    def test_other_providers_only_same_or_one_lower_class_cheaper_at_most_three(self):
        ctx, rec = self.cands(simple_rows(200, model="claude-sonnet-4-5"))      # mid, anthropic
        r = rec["r"]
        self.assertLessEqual(len(r["cands"]), calc.OPEN_MAX_CANDIDATES)
        self.assertTrue(r["cands"])
        for c in r["cands"]:
            self.assertNotEqual(c["provider"], "anthropic")
            self.assertIn(c["cls"], ("mid", "small"))
            self.assertLess(c["repriced"], r["spend"])
        # same class as the route first, then by repriced spend
        keys = [(0 if c["cls"] == "mid" else 1, c["repriced"]) for c in r["cands"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(r["cands"][0]["cls"], "mid")

    def test_candidates_need_200_priced_calls(self):
        _, rec = self.cands(simple_rows(199, model="claude-sonnet-4-5"))
        self.assertEqual(rec["r"]["cands"], [])
        self.assertEqual(rec["r"]["note"], "not enough calls to judge (n=199, under 200).")
        _, rec = self.cands(simple_rows(200, model="claude-sonnet-4-5"))
        self.assertTrue(rec["r"]["cands"])
        text = calc.render(run(simple_rows(150, model="claude-sonnet-4-5"), scope="open"))
        self.assertIn("not enough calls to judge (n=150, under 200)", section(text, "Other providers"))
        self.assertNotIn("| candidate |", section(text, "Other providers"))

    def test_same_class_comes_before_a_cheaper_lower_class(self):
        _, rec = self.cands(simple_rows(200, model="claude-sonnet-4-5"))
        cands = rec["r"]["cands"]
        mids = [c for c in cands if c["cls"] == "mid"]
        smalls = [c for c in cands if c["cls"] == "small"]
        self.assertTrue(mids and smalls)
        self.assertLess(cands.index(mids[0]), cands.index(smalls[0]))
        self.assertGreater(mids[0]["repriced"], smalls[0]["repriced"])      # the mid is dearer but still listed first

    def test_frontier_route_gets_mid_class_but_not_small(self):
        _, rec = self.cands(simple_rows(200, model="claude-opus-5-5"))
        classes = set(c["cls"] for c in rec["r"]["cands"])
        self.assertTrue(classes)
        self.assertLessEqual(classes, {"frontier", "mid"})

    def test_repriced_spend_is_list_price_token_for_token(self):
        _, rec = self.cands(simple_rows(200, model="claude-sonnet-4-5", inp=1000, out=100))
        c = [x for x in rec["r"]["cands"] if x["model"] == "gpt-5-nano"]
        self.assertTrue(c)
        self.assertAlmostEqual(c[0]["repriced"], 200 * (1000 * 0.05 + 100 * 0.40) / 1e6, places=9)
        self.assertAlmostEqual(c[0]["net"], rec["r"]["spend"] - c[0]["repriced"], places=9)
        self.assertEqual(c[0]["added"], 0.0)

    def test_repricing_uses_cached_and_write_rates(self):
        rows = simple_rows(200, model="claude-sonnet-4-5", inp=1000, out=100, cached_input_tokens=400, cache_write_tokens=100)
        ctx, rec = self.cands(rows)
        c = [x for x in rec["r"]["cands"] if x["model"] == "gpt-5-nano"][0]
        want = 200 * (500 * 0.05 + 400 * 0.005 + 100 * 0.05 * 1.0 + 100 * 0.40) / 1e6
        self.assertAlmostEqual(c["repriced"], want, places=9)

    def test_unverified_cache_provider_gets_cached_tokens_at_the_input_rate(self):
        import copy
        self.assertIs(calc.provider_terms(PRICES, "google")["cache_verified"], False)
        self.assertIs(calc.provider_terms(PRICES, "openai")["cache_verified"], True)
        rows = simple_rows(200, model="claude-sonnet-4-5", inp=1000, out=100, cached_input_tokens=400)
        ctx = calc.analyze(calc.parse_rows(rows), PRICES, scope="open")
        idxs = ctx.by_route["r"]
        g = calc.reprice(ctx, idxs, "gemini-3.1-flash-lite")
        self.assertAlmostEqual(g, 200 * (1000 * 0.25 + 100 * 1.50) / 1e6, places=9)       # cached 400 at 0.25, not 0.025
        o = calc.reprice(ctx, idxs, "gpt-5-nano")
        self.assertAlmostEqual(o, 200 * (600 * 0.05 + 400 * 0.005 + 100 * 0.40) / 1e6, places=9)
        p = copy.deepcopy(PRICES)
        p["providers"]["google"]["cache_terms_verified"] = True
        ctx2 = calc.analyze(calc.parse_rows(rows), p, scope="open")
        self.assertAlmostEqual(calc.reprice(ctx2, ctx2.by_route["r"], "gemini-3.1-flash-lite"),
                               200 * (600 * 0.25 + 400 * 0.025 + 100 * 1.50) / 1e6, places=9)

    def test_nothing_cheaper_means_no_candidates(self):
        _, rec = self.cands(simple_rows(200, model="gpt-5-nano"))
        self.assertEqual(rec["r"]["cands"], [])

    def test_section_states_hypothesis_zero_floor_switching_cost_and_eval(self):
        text = calc.render(run(simple_rows(200, model="claude-sonnet-4-5"), scope="open"))
        sec = section(text, "Other providers")
        self.assertIn("HYPOTHESIS", sec)
        self.assertIn("| if fully switched (monthly, high end) |", sec)
        self.assertNotIn("monthly range", sec)
        self.assertIn("up to $", sec)
        self.assertIn("The candidates in each route are alternatives: pick at most one; their figures do not add.", sec)
        self.assertIn("Token counts differ between providers' tokenizers; re-pricing uses this export's token counts, so a real bill can differ.", sec)
        self.assertIn("hand-set price band", sec)
        self.assertIn("new vendor and key", sec)
        self.assertIn("goes to a provider not in this export", sec)
        self.assertIn("replay 100-200 logged calls of this route", sec)
        self.assertIn("limited to the models priced in prices.json", sec)
        self.assertIn("same under --scope stay", sec)

    def test_vendor_already_in_the_export_is_said_so(self):
        rows = simple_rows(200, model="claude-sonnet-4-5") + simple_rows(200, route="o", model="gpt-4o")
        text = calc.render(run(rows, scope="open"))
        self.assertIn("openai is already in this export", text)


class DecisionShapedTests(unittest.TestCase):
    def ctx_for(self, rows, routes_doc=None, prices=None):
        ctx = calc.analyze(calc.parse_rows(rows), prices or PRICES, scope="open")
        if routes_doc:
            ctx.routes_doc = routes_doc
        return ctx

    def test_detection_rule(self):
        self.assertTrue(self.ctx_for(simple_rows(50, model="gpt-4o", out=5)) and
                        calc.decision_shaped(self.ctx_for(simple_rows(50, model="gpt-4o", out=5)), "r"))
        self.assertFalse(calc.decision_shaped(self.ctx_for(simple_rows(49, model="gpt-4o", out=2)), "r"))
        self.assertFalse(calc.decision_shaped(self.ctx_for(simple_rows(200, model="gpt-4o", out=6)), "r"))

    def test_routes_json_flag_marks_a_small_route(self):
        ctx = self.ctx_for(simple_rows(10, model="gpt-4o", out=200))
        self.assertFalse(calc.decision_shaped(ctx, "r"))
        ctx.routes_doc = {"routes": [{"id": "r", "decision_shaped": True}]}
        self.assertTrue(calc.decision_shaped(ctx, "r"))

    def test_cheapest_priced_decision_model_is_first_candidate_net_of_gate(self):
        ctx = self.ctx_for(simple_rows(200, model="gpt-4o", inp=1000, out=2))
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        first = [c for c in rec["cands"] if c["kind"] == "gate"][0]
        self.assertEqual(first["model"], calc.cheapest_decision_model(PRICES))
        self.assertEqual(first["model"], "jev-1.14.0")
        self.assertEqual(first["kind"], "gate")
        cur = rec["spend"]
        added = 200 * 1000 * 0.042 / 1e6
        self.assertAlmostEqual(first["added"], added, places=9)
        self.assertAlmostEqual(first["gross"], cur, places=9)          # no flag: the 0% pass-through ceiling
        self.assertAlmostEqual(first["net"], first["gross"] - added, places=9)
        self.assertAlmostEqual(first["breakeven"], 1 - added / cur, places=9)

    def test_gate_candidate_follows_same_class_candidates(self):
        ctx = self.ctx_for(simple_rows(200, model="gpt-4o", inp=1000, out=2))
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        kinds = [c["kind"] for c in rec["cands"]]
        self.assertIn("gate", kinds)
        self.assertEqual(rec["cands"][0]["cls"], "mid")
        self.assertLessEqual(len(rec["cands"]), calc.OPEN_MAX_CANDIDATES)

    def test_report_prints_ceiling_and_break_even_without_the_flag(self):
        text = calc.render(run(simple_rows(200, model="gpt-4o", inp=1000, out=2), scope="open"))
        sec = section(text, "Other providers")
        self.assertIn("net of gate (ceiling: assumes the gate decides every call)", sec)
        self.assertIn("Break-even pass-through share: 98.3%", sec)
        self.assertIn("--gate-pass-through FRACTION", sec)
        self.assertIn("exact match", sec)
        self.assertNotIn("assumption A2", text)
        self.assertNotIn("10%", sec)

    def test_gate_pass_through_is_used_when_given(self):
        rows = simple_rows(200, model="gpt-4o", inp=1000, out=2)
        ctx = calc.analyze(calc.parse_rows(rows), PRICES, scope="open", gate_pass_through=0.25)
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        gate = [c for c in rec["cands"] if c["kind"] == "gate"][0]
        cur = rec["spend"]
        self.assertAlmostEqual(gate["gross"], 0.75 * cur, places=9)
        self.assertAlmostEqual(gate["net"], 0.75 * cur - gate["added"], places=9)
        sec = section(calc.render(ctx), "Other providers")
        self.assertIn("at your 25.0% pass-through", sec)
        self.assertIn("measured pass-through of 25.0%", sec)
        self.assertNotIn("ceiling", sec)

    def test_break_even_is_where_net_saving_is_zero(self):
        rows = simple_rows(200, model="gpt-4o", inp=1000, out=2)
        base = calc.analyze(calc.parse_rows(rows), PRICES, scope="open")
        be = [c for r in calc.open_candidates(base) for c in r["cands"] if c["kind"] == "gate"][0]["breakeven"]
        ctx = calc.analyze(calc.parse_rows(rows), PRICES, scope="open", gate_pass_through=be)
        gate = [c for r in calc.open_candidates(ctx) for c in r["cands"] if c["kind"] == "gate"][0]
        self.assertAlmostEqual(gate["net"], 0.0, places=9)
        worse = calc.analyze(calc.parse_rows(rows), PRICES, scope="open", gate_pass_through=min(1.0, be + 0.01))
        gate = [c for r in calc.open_candidates(worse) for c in r["cands"] if c["kind"] == "gate"][0]
        self.assertLess(gate["net"], 0)
        self.assertIn("the gate costs more than it saves", calc.render(worse))

    def test_gate_pass_through_must_be_a_fraction(self):
        rows = calc.parse_rows(simple_rows(5))
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                calc.analyze(rows, PRICES, scope="open", gate_pass_through=bad)
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "r.jsonl")
            with open(src, "w", encoding="utf-8") as f:
                f.write("\n".join(json.dumps(r) for r in simple_rows(5)) + "\n")
            with self.assertRaises(SystemExit):
                calc.main([src, "-o", os.path.join(d, "o.md"), "--scope", "open", "--gate-pass-through", "2"])
            calc.main([src, "-o", os.path.join(d, "o.md"), "--scope", "open", "--gate-pass-through", "0.4"])

    def test_headline_and_action_table_ignore_the_pass_through(self):
        rows = simple_rows(200, model="gpt-4o", inp=1000, out=2)
        a = calc.render(calc.analyze(calc.parse_rows(rows), PRICES, scope="open"))
        b = calc.render(calc.analyze(calc.parse_rows(rows), PRICES, scope="open", gate_pass_through=0.5))
        self.assertEqual(line1(a), line1(b))
        self.assertEqual(action_table(a), action_table(b))

    def test_gate_that_costs_more_than_it_saves_shows_zero(self):
        import copy
        p = copy.deepcopy(PRICES)
        p["models"]["dec-x"] = dict(provider="zz", **{"class": "decision", "input": 2.4, "output": 0.0, "cached": 2.4})
        p["models"]["jev-1.14.0"]["class"] = "mid"          # dec-x is now the only decision model
        p["models"]["gemini-decision-1"]["class"] = "mid"
        rows = simple_rows(200, model="gpt-4o", inp=1000, out=2)
        ctx = calc.analyze(calc.parse_rows(rows), p, scope="open", gate_pass_through=0.10)
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        gate = [c for c in rec["cands"] if c["kind"] == "gate"][0]
        self.assertEqual(gate["model"], "dec-x")
        self.assertLess(gate["net"], 0)
        text = calc.render(ctx)
        self.assertIn("the gate costs more than it saves", text)
        self.assertIn("up to $0.00 net of gate", text)

    def test_route_already_on_the_cheapest_decision_model_says_so(self):
        rows = simple_rows(200, model="jev-1.14.0", inp=500, out=0)
        ctx = self.ctx_for(rows)
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        self.assertEqual(rec["cands"], [])
        self.assertIn("already on the cheapest priced decision model", rec["note"])

    def test_small_routes_get_no_decision_candidate(self):
        ctx = self.ctx_for(simple_rows(40, model="gpt-4o", inp=1000, out=2))
        rec = [r for r in calc.open_candidates(ctx) if r["route"] == "r"][0]
        self.assertNotIn("gate", [c["kind"] for c in rec["cands"]])


class NetOfAddedCallsTests(unittest.TestCase):
    def test_net_is_gross_minus_added(self):
        r = calc.net_of_added_calls(10.0, 2.5)
        self.assertEqual((r["gross"], r["added"], r["net"]), (10.0, 2.5, 7.5))
        self.assertEqual(calc.net_of_added_calls(1.0, 3.0)["net"], -2.0)


class ToolSchemaTests(unittest.TestCase):
    def rows(self, n=100, unused=100, sessions=5, schema=2000, **extra):
        rows = simple_rows(n, model="claude-sonnet-4-5", inp=5000, out=100, tools_defined=9, tool_schema_tokens=schema, **extra)
        for i, r in enumerate(rows):
            r["tool_calls"] = 0 if i < unused else 1
            if sessions is not None:
                r["session_id"] = "s%d" % (i % sessions)
            else:                                   # task_id is read as the session when there is no session_id column
                del r["session_id"]
                del r["task_id"]
        return rows

    def test_dollars_use_uncached_rate_and_are_measured(self):
        ctx = run(self.rows())
        self.assertEqual(len(ctx.tool_findings), 1)
        f = ctx.tool_findings[0]
        self.assertAlmostEqual(f["usd"], 100 * 2000 * 3.00 / 1e6, places=9)
        self.assertEqual((f["n"], f["unused"]), (100, 100))

    def test_cached_tokens_covering_the_schema_use_the_cached_rate(self):
        ctx = run(self.rows(cached_input_tokens=3000))
        self.assertAlmostEqual(ctx.tool_findings[0]["usd"], 100 * 2000 * 0.30 / 1e6, places=9)
        self.assertEqual(ctx.tool_findings[0]["n_cached"], 100)

    def test_threshold_is_ninety_percent_of_schema_carrying_calls(self):
        self.assertEqual(len(run(self.rows(unused=90)).tool_findings), 1)
        self.assertEqual(run(self.rows(unused=89)).tool_findings, [])

    def test_route_needs_50_schema_carrying_calls(self):
        self.assertEqual(run(self.rows(n=49, unused=49)).tool_findings, [])
        self.assertEqual(len(run(self.rows(n=50, unused=50)).tool_findings), 1)
        thin = run(self.rows(n=49, unused=49))
        self.assertEqual((thin.tool_checked, thin.tool_thin), (0, 1))
        self.assertIn("1 route not judged: under 50 calls", calc.render(thin))
        # calls with no schema do not count towards the 50
        rows = self.rows(n=60, unused=60)
        for r in rows[:20]:
            r["tool_schema_tokens"] = 0
        self.assertEqual(run(rows).tool_findings, [])

    def test_wording_matches_what_is_checked(self):
        sec = section(calc.render(run(self.rows())), "Unused tool schemas")
        self.assertNotIn("on every call", sec)
        self.assertIn("calls that carry a tool schema and a tool-call count (at least 50 of them)", sec)

    def test_needs_two_sessions_when_session_ids_exist(self):
        self.assertEqual(run(self.rows(sessions=1)).tool_findings, [])
        self.assertEqual(len(run(self.rows(sessions=2)).tool_findings), 1)

    def test_no_session_ids_still_reports_and_says_sessions_not_logged(self):
        ctx = run(self.rows(sessions=None))
        self.assertEqual(len(ctx.tool_findings), 1)
        self.assertIn("sessions not logged", calc.render(ctx))

    def test_rows_without_tool_columns_or_schema_are_not_counted(self):
        self.assertFalse(run(simple_rows(50)).tool_cols)
        self.assertNotIn("Unused tool schemas", calc.render(run(simple_rows(50))))
        self.assertEqual(run(self.rows(schema=0)).tool_findings, [])

    def test_section_labels_and_assumption(self):
        sec = section(calc.render(run(self.rows())), "Unused tool schemas")
        self.assertIn("MEASURED", sec)
        self.assertIn("HYPOTHESIS: drop or defer unused tool definitions", sec)
        self.assertIn("uncached input rate", sec)

    def test_finding_is_outside_the_totals(self):
        with_cols, without = run(self.rows()), run([dict((k, v) for k, v in r.items() if not k.startswith("tool")) for r in self.rows()])
        self.assertAlmostEqual(with_cols.low_total, without.low_total, places=9)
        self.assertAlmostEqual(with_cols.high_total, without.high_total, places=9)
        agg = calc.money_table(with_cols)
        self.assertAlmostEqual(sum(sum(v[1:]) for v in agg.values()), with_cols.spend, places=6)

    def test_schema_tokens_cannot_exceed_the_call_input(self):
        ctx = run(self.rows(schema=9000))
        self.assertAlmostEqual(ctx.tool_findings[0]["usd"], 100 * 5000 * 3.00 / 1e6, places=9)


class SpiralTests(unittest.TestCase):
    def rows(self, n_tasks=25, spiral_calls=8, failed=3):
        rows, t = [], 1_700_000_000
        for k in range(n_tasks):
            for j in range(2):
                t += 30
                rows.append(dict(timestamp=t, route="agent", model="claude-sonnet-4-5", input_tokens=1000, output_tokens=100,
                                 task_id="t%02d" % k, success="true"))
        for j in range(spiral_calls):
            t += 30
            rows.append(dict(timestamp=t, route="agent", model="claude-sonnet-4-5", input_tokens=1000, output_tokens=100,
                             task_id="spiral", success="false" if j < failed else "true"))
        return rows

    def test_spiral_is_counted_with_its_spend(self):
        ctx = run(self.rows())
        r = ctx.spiral_rows[0]
        self.assertEqual((r["route"], r["n"], r["calls"]), ("agent", 1, 8))
        self.assertAlmostEqual(r["spend"], 8 * (1000 * 3.00 + 100 * 15.00) / 1e6, places=9)
        self.assertEqual(r["tasks"], 26)

    def test_needs_two_failed_calls_and_a_long_task(self):
        self.assertEqual(run(self.rows(failed=1)).spiral_rows[0]["n"], 0)
        self.assertEqual(run(self.rows(spiral_calls=5, failed=3)).spiral_rows[0]["n"], 0)       # 5 calls is not above 2.5 x 2
        self.assertEqual(run(self.rows(spiral_calls=6, failed=2)).spiral_rows[0]["n"], 1)

    def one_call_route(self, loop_calls, failed=2, n_tasks=25):
        rows, t = [], 1_700_000_000
        for k in range(n_tasks):
            t += 30
            rows.append(dict(timestamp=t, route="gate", model="claude-sonnet-4-5", input_tokens=1000, output_tokens=100,
                             task_id="t%02d" % k, success="true"))
        for j in range(loop_calls):
            t += 30
            rows.append(dict(timestamp=t, route="gate", model="claude-sonnet-4-5", input_tokens=1000, output_tokens=100,
                             task_id="loop", success="false" if j < failed else "true"))
        return rows

    def test_one_call_median_route_needs_four_calls_in_a_spiral_task(self):
        r = run(self.one_call_route(3)).spiral_rows[0]
        self.assertEqual(r["med_calls"], 1)
        self.assertEqual(r["n"], 0)                    # 3 calls is above 2.5 x 1, but not a loop on a one-call route
        self.assertEqual(run(self.one_call_route(4)).spiral_rows[0]["n"], 1)
        self.assertEqual(run(self.one_call_route(4, failed=1)).spiral_rows[0]["n"], 0)
        # the 4-call rule is only for a median of 1: a median-2 route keeps 6 calls
        self.assertEqual(run(self.rows(spiral_calls=6, failed=2)).spiral_rows[0]["n"], 1)
        self.assertIn("at least 4 calls", section(calc.render(run(self.one_call_route(4))), "Spirals"))

    def test_zero_spiral_routes_print_no_row(self):
        ctx = run(self.rows(spiral_calls=5, failed=3))
        self.assertEqual(ctx.spiral_rows[0]["n"], 0)
        sec = section(calc.render(ctx), "Spirals")
        self.assertNotIn("| agent |", sec)
        self.assertIn("1 route judged; no task met the spiral rule.", sec)
        sec = section(calc.render(run(self.rows())), "Spirals")
        self.assertIn("| agent |", sec)

    def test_tokens_alone_can_make_a_spiral(self):
        rows = self.rows(spiral_calls=2, failed=2)
        for r in rows:
            if r["task_id"] == "spiral":
                r["input_tokens"] = 20000
        self.assertEqual(run(rows).spiral_rows[0]["n"], 1)

    def test_not_enough_tasks(self):
        ctx = run(self.rows(n_tasks=18))               # 19 tasks with the spiral candidate
        self.assertEqual(ctx.spiral_rows, [])
        self.assertEqual(ctx.spiral_thin, [("agent", 19)])
        self.assertIn("Not enough tasks", calc.render(ctx))
        self.assertEqual(len(run(self.rows(n_tasks=19)).spiral_rows), 1)

    def test_section_is_measured_and_outside_totals(self):
        text = calc.render(run(self.rows()))
        sec = section(text, "Spirals")
        self.assertIn("MEASURED", sec)
        self.assertIn("in no total", sec)
        self.assertIn("1 (3.8% of tasks)", sec)

    def test_no_success_column_means_no_judgement(self):
        rows = self.rows()
        for r in rows:
            del r["success"]
        text = calc.render(run(rows))
        self.assertIn("no success column, so failed calls cannot be counted", text)

    def test_routes_without_task_ids_are_left_out(self):
        rows = simple_rows(40)
        for r in rows:
            del r["task_id"]
            del r["session_id"]
        ctx = calc.analyze(calc.parse_rows(rows), PRICES)
        self.assertEqual((ctx.spiral_rows, ctx.spiral_thin), ([], []))


class EvidenceRuleTests(unittest.TestCase):
    def failing_rows(self, sessions):
        rows = simple_rows(250, model="claude-sonnet-4-5")
        for i, r in enumerate(rows):
            r["session_id"] = "s%d" % (i % sessions)
            r["success"] = "false" if i % 10 == 0 else "true"
        return rows

    def test_helper(self):
        self.assertEqual(calc.low_evidence(set()), (False, 0))
        self.assertEqual(calc.low_evidence({"a", "b"}), (True, 2))
        self.assertEqual(calc.low_evidence({"a", "b", "c"}), (False, 3))
        self.assertEqual(calc.evidence_note({"a"}), ", low evidence (1 session)")

    def test_action_table_marks_findings_on_fewer_than_three_sessions(self):
        text = calc.render(run(self.failing_rows(2)))
        row = [l for l in text.splitlines() if l.startswith("| 1 |") or "Stop paying for failed calls" in l][0]
        self.assertIn("low evidence (2 sessions)", row)

    def test_three_or_more_sessions_are_not_marked(self):
        text = calc.render(run(self.failing_rows(3)))
        self.assertNotIn("low evidence (", action_table(text))

    def test_no_session_id_column_is_not_marked(self):
        rows = self.failing_rows(2)
        for r in rows:
            del r["session_id"]
            del r["task_id"]                        # task_id is read as the session when there is no session_id column
        ctx = calc.analyze(calc.parse_rows(rows), PRICES)
        self.assertNotIn("low evidence (", calc.render(ctx).split("## Method")[0].split("Ranked by")[0])

    def test_tool_finding_with_two_sessions_is_marked_low(self):
        rows = ToolSchemaTests().rows(sessions=2)
        sec = section(calc.render(run(rows)), "Unused tool schemas")
        self.assertIn("low evidence", sec)

    def test_legend_is_in_the_report(self):
        self.assertIn("Low evidence", calc.render(run(make_rows())))


class NewColumnRowTests(unittest.TestCase):
    def test_check_rows_accepts_counts_and_rejects_junk(self):
        import check_rows
        good = dict(model="claude-sonnet-4-5", input_tokens=10, output_tokens=5, tools_defined=3, tool_schema_tokens=900, tool_calls=0)
        self.assertEqual(check_rows.row_problems(good), [])
        for col, val in (("tool_calls", -1), ("tools_defined", "many"), ("tool_schema_tokens", True)):
            self.assertTrue(any(col in p for p in check_rows.row_problems(dict(good, **{col: val}))), col)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rows.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(good) + "\n")
            self.assertEqual(check_rows.check_rows(p), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
