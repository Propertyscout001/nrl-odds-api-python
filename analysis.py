#!/usr/bin/env python3
"""Read the CSV with stdlib csv and report how far apart the bookmakers are.

    python3 analysis.py                        # reads data/nrl_odds.csv
    python3 analysis.py data/nrl_history.csv --latest
    python3 analysis.py data/nrl_odds.csv --market spreads

No pandas, no numpy -- this deliberately uses only `csv` so it runs on a bare
system Python and so the grouping logic is visible rather than hidden inside a
one-line groupby.

What it measures
----------------
For every (fixture, market, line, selection) it reports the highest and lowest
decimal price currently offered across the books that priced it, and the gap
between them:

    spread % = (max_price / min_price - 1) * 100

That is a dispersion measure of the data feed. It says the books disagree; it
does not say anything about outcomes, and a wide gap is just as likely to mean
one book is slow to update as it is to mean anything else -- which is why the
`oldest` column prints the age of the stalest quote in the comparison.

Lines are grouped by `point`, not just by market. Comparing a -6.5 spread price
at one book against a -7.5 at another is comparing two different bets.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

from pe_nrl import SIGNUP_URL


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Report bookmaker price dispersion from a tidy NRL odds CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("csv_path", nargs="?", default="data/nrl_odds.csv", help="input CSV")
    p.add_argument(
        "--market",
        default="h2h",
        help="market to report: h2h (default), spreads, totals, or 'all'",
    )
    p.add_argument(
        "--latest",
        action="store_true",
        help="for a history file, keep only the most recent snapshot",
    )
    p.add_argument(
        "--min-books",
        type=int,
        default=2,
        help="skip selections priced by fewer than this many books (default 2)",
    )
    return p.parse_args(argv)


def load(path, market, latest):
    if not os.path.exists(path):
        sys.stderr.write(
            "No such file: %s\nRun `python3 fetch_nrl.py --demo` first.\n" % path
        )
        raise SystemExit(2)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    if latest:
        newest = max(r.get("fetched_at", "") for r in rows)
        rows = [r for r in rows if r.get("fetched_at", "") == newest]
    if market != "all":
        rows = [r for r in rows if r.get("market") == market]
    out = []
    for r in rows:
        try:
            r["_price"] = float(r["price"])
        except (TypeError, ValueError):
            continue
        try:
            r["_age"] = int(float(r["book_age_seconds"]))
        except (TypeError, ValueError):
            r["_age"] = None
        out.append(r)
    return out


def group(rows):
    """One bucket per comparable bet. `point` is in the key on purpose."""
    buckets = defaultdict(list)
    for r in rows:
        key = (
            r["event_id"],
            r["commence_time"],
            r["home"],
            r["away"],
            r["market"],
            r.get("point", ""),
            r["selection_side"],
        )
        buckets[key].append(r)
    return buckets


def fmt_age(seconds):
    if seconds is None:
        return "  n/a"
    if seconds < 90:
        return "%3ds" % seconds
    if seconds < 5400:
        return "%3dm" % (seconds // 60)
    return "%3dh" % (seconds // 3600)


def main(argv=None):
    args = parse_args(argv)
    rows = load(args.csv_path, args.market, args.latest)
    if not rows:
        print("No usable rows in %s for market=%s." % (args.csv_path, args.market))
        return 0

    buckets = group(rows)
    by_event = defaultdict(list)
    for key, items in buckets.items():
        by_event[key[:4]].append((key[4], key[5], key[6], items))

    comparable = sum(1 for items in buckets.values() if len(items) >= args.min_books)
    skipped = len(buckets) - comparable

    print("source        %s" % args.csv_path)
    print("market        %s" % args.market)
    print(
        "comparisons   %d of %d selection(s) priced by >= %d book(s), across %d fixture(s)"
        % (comparable, len(buckets), args.min_books, len(by_event))
    )
    if skipped:
        print("skipped       %d selection(s) priced by only one book" % skipped)
    print()

    if not comparable:
        print(
            "Nothing to compare: every selection in this file carries a price from a\n"
            "single bookmaker only.\n"
        )
        print(
            "That is the expected result for a --demo CSV. The keyless demo endpoint\n"
            "returns the BEST price per selection, not each book's price, so there is\n"
            "no dispersion in it to measure. Fetch with an API key to compare books:\n"
            "  export PE_API_KEY=...\n"
            "  python3 fetch_nrl.py --markets h2h -o data/nrl_odds.csv\n"
            "  python3 analysis.py data/nrl_odds.csv\n"
        )
        print("Free key (1,500 credits/month, no card):")
        print("  " + SIGNUP_URL)
        return 0

    widest = None
    for ev_key in sorted(by_event, key=lambda k: k[1]):
        _eid, commence, home, away = ev_key
        rows_here = [
            t for t in by_event[ev_key] if len(t[3]) >= args.min_books
        ]
        if not rows_here:
            continue
        print("%s  vs  %s" % (home, away))
        print("  kicks off %s" % commence)
        print(
            "  %-8s %-6s %-6s %8s %-13s %8s %-13s %8s %6s"
            % ("market", "line", "side", "best", "book", "worst", "book", "spread%", "oldest")
        )
        for market, point, side, items in sorted(
            rows_here, key=lambda t: (t[0], str(t[1]), t[2])
        ):
            hi = max(items, key=lambda r: r["_price"])
            lo = min(items, key=lambda r: r["_price"])
            spread = (hi["_price"] / lo["_price"] - 1.0) * 100.0 if lo["_price"] else 0.0
            ages = [r["_age"] for r in items if r["_age"] is not None]
            oldest = max(ages) if ages else None
            print(
                "  %-8s %-6s %-6s %8.2f %-13s %8.2f %-13s %7.2f%% %6s"
                % (
                    market,
                    point if point not in ("", None) else "-",
                    side,
                    hi["_price"],
                    hi["bookmaker"],
                    lo["_price"],
                    lo["bookmaker"],
                    spread,
                    fmt_age(oldest),
                )
            )
            if widest is None or spread > widest[0]:
                widest = (spread, home, away, market, point, side, len(items))
        print()

    if widest:
        spread, home, away, market, point, side, nbooks = widest
        line = (" line %s," % point) if point not in ("", None) else ""
        print(
            "Widest disagreement: %.2f%% on the %s %s selection (%s vs %s,%s %d books)."
            % (spread, market, side, home, away, line, nbooks)
        )
    print(
        "\nSpread % is (best / worst - 1) * 100 across the books that priced the "
        "selection.\nIt describes disagreement in the feed at one moment. Check the "
        "`oldest` column\nbefore reading anything into a wide number -- a stale quote "
        "widens the gap on its own."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
