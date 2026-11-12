#!/usr/bin/env python
"""Generate examples/sample_rows.jsonl: MADE-UP data in this pack's row schema.

Every number below is invented by a seeded random generator (fixed seed), so
the output is the same on every run. The data does not come from any real app,
company or log. It exists so you can run scripts/calc.py and see what the report
looks like. The routes are fake too (see sample_routes.json).

It imitates 14 days of a small app with five routes:

  app/chat.py:reply               streamed, multi-turn sessions, explicit prompt cache
                                  (1-hour cache writes, 5-minute rewrites, cache reads)
  app/extract.py:parse_invoice    back-office, nightly bursts, not streamed, retries
  app/summarize.py:summarise      back-office, a slow trickle all day, not streamed
  app/gate.py:should_escalate     a stateless decision model priced as jev-1.14.0
                                  (input only, output 0), one call per event
  app/warmup.py:keepalive         warm-up calls the log has no token usage for
                                  (rows flagged usage_missing)

Usage: python examples/make_sample.py [out.jsonl]   (default: examples/sample_rows.jsonl)
"""
import hashlib
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

SEED = 24
DAYS = 14
START = datetime(2026, 10, 12, 0, 0, 0, tzinfo=timezone.utc)   # a Monday

R_CHAT = "app/chat.py:reply"
R_EXTRACT = "app/extract.py:parse_invoice"
R_SUMMARY = "app/summarize.py:summarise"
R_GATE = "app/gate.py:should_escalate"
R_WARM = "app/warmup.py:keepalive"

CHAT_PREFIX = 3500
EXTRACT_PREFIX = 6000
SUMMARY_PREFIX = 1500


def lognorm(rng, median, sigma, lo=1, hi=None):
    v = max(lo, int(rng.lognormvariate(math.log(median), sigma)))
    return min(hi, v) if hi else v


def hid(prefix, n):
    return hashlib.sha256(("%s-%d" % (prefix, n)).encode()).hexdigest()[:16]


def phash(route):
    return hashlib.sha256((route + "-system-v7").encode()).hexdigest()[:12]


class Sink(object):
    def __init__(self):
        self.rows = []

    def add(self, t, route, model, inp, out, lat, ttft=None, cached=0, cw=0, cw1=0, task="", session="",
            ok=True, streamed=False, prefix=None, kind=None, stateless=False):
        row = {"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "route": route, "model": model,
               "input_tokens": inp, "output_tokens": out, "latency_ms": int(lat),
               "success": ok, "streamed": streamed}
        if ttft is not None:
            row["ttft_ms"] = int(ttft)
        if cached:
            row["cached_input_tokens"] = cached
        if cw:
            row["cache_write_tokens"] = cw
        if cw1:
            row["cache_write_1h_tokens"] = cw1
        if task:
            row["task_id"] = task
        if session:
            row["session_id"] = session
        if prefix:
            row["prefix_hash"] = phash(route)
            row["prefix_tokens"] = prefix
        if kind:
            row["prefix_hash_kind"] = kind
        if stateless:
            row["stateless"] = True
        row["synthetic"] = True
        self.rows.append(row)


def chat_session(rng, sink, sid, t0):
    """One chat session: the first call writes the 1-hour cache, later calls read it,
    now and then the cache is missed and rewritten (a 5-minute write)."""
    model = "claude-sonnet-5-5"
    t, history = t0, 0
    for turn in range(1, rng.randint(3, 12) + 1):
        user = lognorm(rng, 60, 0.6)
        inp = CHAT_PREFIX + history + user
        out = lognorm(rng, 150, 0.55, lo=3)
        ok = rng.random() > 0.03
        ttft = rng.lognormvariate(math.log(520), 0.3) + inp * 0.03
        if rng.random() < 0.02:
            ttft *= 3.0
        lat = ttft + out * 15 * rng.uniform(0.8, 1.3)
        cached = cw = cw1 = 0
        if turn == 1:
            cw1 = CHAT_PREFIX
        elif rng.random() < 0.08:
            cw = CHAT_PREFIX            # prefix changed or cache missed: written again
        else:
            cached = CHAT_PREFIX
        o = out if ok else max(3, int(out * rng.uniform(0.0, 0.5)))
        sink.add(t, R_CHAT, model, inp, o, lat if ok else lat * 2.2, ttft=ttft, cached=cached, cw=cw, cw1=cw1,
                 task=sid, session=sid, ok=ok, streamed=True, prefix=CHAT_PREFIX, kind="content")
        if not ok:
            return
        history += user + out
        t += timedelta(seconds=rng.randint(15, 90))


def invoice_night(rng, sink, day_start, n_jobs, counter):
    t = day_start + timedelta(hours=1, minutes=rng.randint(0, 20))
    for _ in range(n_jobs):
        counter[0] += 1
        job = hid("inv", counter[0])
        inp = EXTRACT_PREFIX + lognorm(rng, 20000, 0.45, lo=1500, hi=110000)
        out = lognorm(rng, 650, 0.4, lo=60)
        for p_ok in (0.93, 0.6, 0.5):
            ok = rng.random() < p_ok
            o = out if ok else int(out * rng.uniform(1.6, 2.6))     # malformed output runs long
            lat = 900 + o * 18 * rng.uniform(0.8, 1.25)
            sink.add(t, R_EXTRACT, "claude-sonnet-5-5", inp, o, lat if ok else lat * 1.8, task=job, ok=ok,
                     prefix=EXTRACT_PREFIX, kind="content")
            if ok:
                break
            t += timedelta(seconds=rng.randint(3, 8))
        t += timedelta(seconds=rng.uniform(2, 7))


def summary_day(rng, sink, day_start, mean_per_day, counter):
    t = day_start
    gap = 86400.0 / mean_per_day
    while True:
        t += timedelta(seconds=rng.expovariate(1.0 / gap))
        if t >= day_start + timedelta(days=1):
            return
        counter[0] += 1
        tid = hid("tkt", counter[0])
        inp = SUMMARY_PREFIX + lognorm(rng, 1500, 0.5, lo=200, hi=30000)
        out = lognorm(rng, 240, 0.4, lo=20)
        tt = t
        for attempt in (1, 2):
            ok = rng.random() > (0.02 if attempt == 1 else 0.05)
            sink.add(tt, R_SUMMARY, "gpt-4o", inp, out if ok else 5, 700 + out * 17 * rng.uniform(0.8, 1.3),
                     task=tid, ok=ok, prefix=SUMMARY_PREFIX, kind="content")
            if ok:
                break
            tt += timedelta(seconds=rng.randint(5, 20))


def gate_day(rng, sink, day_start, n_events):
    """A per-event decision model: every call stands alone, output is not billed (0)."""
    for i in range(n_events):
        t = day_start + timedelta(seconds=rng.uniform(0, 86399))
        inp = lognorm(rng, 700, 0.35, lo=150, hi=4000)
        sink.add(t, R_GATE, "jev-1.14.0", inp, 0, 90 + inp * 0.05 * rng.uniform(0.8, 1.3),
                 ok=rng.random() > 0.005, prefix=250, kind="structural", stateless=True)


def warmup_day(rng, sink, day_start):
    """Keepalive calls whose log lines carry no token usage."""
    for _ in range(2):
        t = day_start + timedelta(seconds=rng.uniform(0, 86399))
        sink.rows.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "route": R_WARM,
                          "model": "claude-sonnet-5-5", "usage_missing": True,
                          "latency_ms": int(rng.uniform(600, 1400)), "success": True, "synthetic": True})


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "sample_rows.jsonl")
    rng = random.Random(SEED)
    sink = Sink()
    sess_n, inv_n, tkt_n = 0, [0], [0]
    for d in range(DAYS):
        day = START + timedelta(days=d)
        weekend = day.weekday() >= 5
        f = 0.55 if weekend else 1.0
        for _ in range(max(1, int(rng.gauss(40 * f, 4)))):
            sess_n += 1
            hour = min(23.99, max(0.0, rng.gauss(15, 4)))
            chat_session(rng, sink, hid("sess", sess_n), day + timedelta(hours=hour))
        invoice_night(rng, sink, day, max(1, int(rng.gauss(60 * f, 6))), inv_n)
        summary_day(rng, sink, day, 50 * f, tkt_n)
        gate_day(rng, sink, day, int(rng.gauss(250 * f, 20)))
        warmup_day(rng, sink, day)
    sink.rows.sort(key=lambda r: r["timestamp"])
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for row in sink.rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    print("wrote %d MADE-UP rows to %s (seed %d)" % (len(sink.rows), out_path, SEED))


if __name__ == "__main__":
    main()
