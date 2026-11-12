#!/usr/bin/env python
"""Leak check: do any phrases taken from the app's own logs or prompts appear in the audit outputs?

    python privacy_check.py PATH [PATH ...] --phrases-file FILE [--phrases-file FILE ...] [--min-chars N]

PATH is a file or a folder (searched recursively): rows.jsonl, report.md, diagnosis.md, adapter.py,
or the whole work/<repo>/ folder. FILE holds one phrase per line (distinctive text lifted from the
app's logs or prompts, or raw task / session ids). Matching ignores case and runs of whitespace, and
also tries the JSON-escaped form, so it finds a phrase inside a .jsonl value too.

Output names the phrase by its file and line number and its word count, plus the file that holds it
and how many times. It never prints a phrase or any text around a hit. The phrases file itself is
never searched. Exit 0 = no hits, 1 = hits, 2 = nothing to check.

Keep the phrases file outside work/ (the OS temp folder) and delete it when the check is done: it holds
the very text the check protects.
"""
import argparse
import json
import os
import re
import sys

MAX_BYTES = 50 * 1024 * 1024
WS = re.compile(r"\s+")
ESCAPED_WS = re.compile(r"\\[nrt]")


def norm(s):
    return WS.sub(" ", s.strip().lower())


def load_phrases(files, min_chars):
    """List of (label, word count, variants) and the number of phrases skipped as too short."""
    out, skipped = [], 0
    for pf in files:
        with open(pf, encoding="utf-8", errors="replace") as f:
            for ln, line in enumerate(f, 1):
                p = norm(line)
                if not p:
                    continue
                if len(p) < min_chars:
                    skipped += 1
                    continue
                variants = {p, norm(json.dumps(p, ensure_ascii=False)[1:-1]), norm(json.dumps(p)[1:-1])}
                out.append(("%s line %d" % (os.path.basename(pf), ln), len(p.split()), sorted(variants)))
    return out, skipped


def collect(paths, skip):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    files.append(os.path.join(root, n))
        elif os.path.isfile(p):
            files.append(p)
    return [f for f in files if os.path.realpath(f) not in skip]


def find_hits(paths, phrase_files, min_chars=4):
    """(hits, n_phrases, n_skipped, n_files). A hit is (phrase label, word count, file, count)."""
    skip = set(os.path.realpath(p) for p in phrase_files)
    phrases, skipped = load_phrases(phrase_files, min_chars)
    files = collect(paths, skip)
    hits = []
    for fp in files:
        if os.path.getsize(fp) > MAX_BYTES:
            continue
        with open(fp, encoding="utf-8", errors="replace") as f:
            body = norm(ESCAPED_WS.sub(" ", f.read()))      # a newline inside a JSON string is the two characters \n
        for label, words, variants in phrases:
            n = max(body.count(v) for v in variants)
            if n:
                hits.append((label, words, fp, n))
    return hits, len(phrases), skipped, len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="files or folders to search")
    ap.add_argument("--phrases-file", action="append", default=[], required=True,
                    help="file with one phrase or raw id per line (repeatable)")
    ap.add_argument("--min-chars", type=int, default=4, help="skip phrases shorter than this (too noisy); default 4")
    a = ap.parse_args(argv)
    for pf in a.phrases_file:
        if not os.path.isfile(pf):
            print("error: phrases file not found: %s" % pf)
            return 2
    hits, n_phr, skipped, n_files = find_hits(a.paths, a.phrases_file, a.min_chars)
    if n_phr == 0 or n_files == 0:
        print("error: nothing to check (%d phrases, %d files searched)" % (n_phr, n_files))
        return 2
    for label, words, fp, n in hits:
        print("HIT: phrase at %s (%d words) found %d time%s in %s" % (label, words, n, "" if n == 1 else "s", fp))
    print("%s: %d phrases (%d skipped as shorter than %d characters), %d files searched, %d hits"
          % ("FAIL" if hits else "OK", n_phr, skipped, a.min_chars, n_files, len(hits)))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
