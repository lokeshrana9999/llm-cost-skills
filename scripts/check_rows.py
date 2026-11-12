#!/usr/bin/env python
"""Privacy check for rows.jsonl: only the calc.py columns, only numbers and short opaque strings.

    python check_rows.py rows.jsonl [--forbid TEXT ...] [--also FILE ...]

Fails (exit 1) on a column outside the allowlist, a string value that is long or has
whitespace (outside timestamp), or any --forbid text found in rows.jsonl or --also files.
"""
import argparse
import json
import sys

ALLOWED = {
    "model", "input_tokens", "output_tokens", "route", "timestamp", "cached_input_tokens", "cache_write_tokens",
    "cache_write_1h_tokens", "ttft_ms", "latency_ms", "success", "streamed", "task_id", "session_id",
    "prefix_hash", "prefix_tokens", "synthetic", "usage_missing", "stateless", "prefix_hash_kind", "logged_cost_usd",
    "tools_defined", "tool_schema_tokens", "tool_calls",
}
COUNT_COLS = ("tools_defined", "tool_schema_tokens", "tool_calls")
MAX_STR = 96
TOKEN_COLS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "cache_write_1h_tokens")
BOOL_COLS = ("usage_missing", "stateless")


def _truthy(v):
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"))


def _is_bool(v):
    return isinstance(v, bool) or (isinstance(v, str) and v.strip().lower() in ("true", "false", "1", "0", "yes", "no"))


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def row_problems(row):
    """Value-level problems of one row (types, enum, required columns); ids and text are checked separately."""
    out = []
    for k in BOOL_COLS:
        if k in row and not _is_bool(row[k]):
            out.append("column %r must be true or false" % k)
    if "prefix_hash_kind" in row and row["prefix_hash_kind"] not in ("content", "structural"):
        out.append("column 'prefix_hash_kind' must be content or structural")
    if "logged_cost_usd" in row and row["logged_cost_usd"] is not None and not _is_num(row["logged_cost_usd"]):
        out.append("column 'logged_cost_usd' must be a number")
    for k in COUNT_COLS:
        if k in row and row[k] is not None and (not _is_num(row[k]) or row[k] < 0):
            out.append("column %r must be a count (a number, 0 or more)" % k)
    if _truthy(row.get("usage_missing")):
        if any(row.get(c) not in (None, "") for c in TOKEN_COLS):
            out.append("row is usage_missing but carries token counts; drop the flag or the counts")
    else:
        for c in ("model", "input_tokens", "output_tokens"):
            if row.get(c) in (None, ""):
                out.append("column %r is required unless usage_missing is true" % c)
    return out


def check_rows(path):
    """List of problems found in a rows.jsonl file (empty list = clean)."""
    problems, n = [], 0
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                row = json.loads(line)
            except ValueError:
                problems.append("line %d: not JSON" % ln)
                continue
            if not isinstance(row, dict):
                problems.append("line %d: not an object" % ln)
                continue
            problems += ["line %d: %s" % (ln, p) for p in row_problems(row)]
            for k, v in row.items():
                if k not in ALLOWED:
                    problems.append("line %d: column %r is not in the schema" % (ln, k))
                elif isinstance(v, (dict, list)):
                    problems.append("line %d: column %r holds a nested value" % (ln, k))
                elif isinstance(v, str):
                    if len(v) > MAX_STR:
                        problems.append("line %d: column %r has a %d-character string" % (ln, k, len(v)))
                    elif k != "timestamp" and any(ch.isspace() for ch in v):
                        problems.append("line %d: column %r has whitespace in %r" % (ln, k, v[:30]))
            if len(problems) > 20:
                problems.append("... stopping after 20 problems")
                return problems
    if n == 0:
        problems.append("no rows")
    return problems


def find_text(paths, forbid):
    out = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            body = f.read().lower()
        for t in forbid:
            if t.lower() in body:
                out.append("%s contains forbidden text %r" % (p, t))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rows")
    ap.add_argument("--forbid", action="append", default=[], help="text that must not appear (repeatable)")
    ap.add_argument("--also", action="append", default=[], help="extra file to scan for --forbid text")
    a = ap.parse_args(argv)
    problems = check_rows(a.rows) + find_text([a.rows] + a.also, a.forbid)
    if problems:
        print("FAIL")
        for p in problems:
            print(" - " + p)
        return 1
    print("OK: %s holds only schema columns and short opaque values" % a.rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
