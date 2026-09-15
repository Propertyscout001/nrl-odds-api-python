#!/usr/bin/env python3
"""Pull NRL fixtures + bookmaker odds and write one tidy CSV row per price.

    python3 fetch_nrl.py --demo                  # no API key needed
    python3 fetch_nrl.py                         # needs PUNTERSEDGE_API_KEY
    python3 fetch_nrl.py --markets h2h,spreads,totals -o data/nrl.csv
    python3 fetch_nrl.py --sport nrlw            # nrlw / super_league also work

Output is long-format ("tidy"): one row per (event, bookmaker, market, selection).
That is the shape pandas, DuckDB and a database table all want:

    import pandas as pd
    df = pd.read_csv("data/nrl_odds.csv")
    df.pivot_table(index=["event_id","selection_side"],
                   columns="bookmaker", values="price")
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

import pe_nrl


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Fetch NRL odds from the PuntersEdge API into a tidy CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Free API key (1,500 credits/month, no card): " + pe_nrl.SIGNUP_URL,
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="use the keyless demo endpoint (0 credits, best price per selection only)",
    )
    p.add_argument(
        "--sport",
        default="nrl",
        help="sport_key: nrl (default), nrlw, super_league",
    )
    p.add_argument(
        "--markets",
        default="h2h",
        help="comma-separated: h2h (default), spreads, totals. Ignored with --demo.",
    )
    p.add_argument(
        "-o",
        "--out",
        default="data/nrl_odds.csv",
        help="CSV path to write (default: data/nrl_odds.csv). Use - for stdout.",
    )
    p.add_argument(
        "--quiet", action="store_true", help="suppress the summary written to stderr"
    )
    return p.parse_args(argv)


def write_csv(path, rows):
    if path == "-":
        writer = csv.DictWriter(sys.stdout, fieldnames=pe_nrl.FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=pe_nrl.FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def summarise(rows, source, cost, path, out=sys.stderr):
    events = {r["event_id"] for r in rows}
    books = sorted({r["bookmaker"] for r in rows if r["bookmaker"]})
    markets = Counter(r["market"] for r in rows)
    unknown = sum(1 for r in rows if r["selection_side"] == "unknown")

    out.write("source        %s\n" % source)
    out.write("credit cost   %s\n" % (cost if cost is not None else "unknown"))
    out.write("rows          %d\n" % len(rows))
    out.write("fixtures      %d\n" % len(events))
    out.write(
        "bookmakers    %d (%s)\n" % (len(books), ", ".join(books) if books else "-")
    )
    out.write(
        "markets       %s\n"
        % (", ".join("%s=%d" % kv for kv in sorted(markets.items())) or "-")
    )
    if unknown:
        out.write(
            "WARNING       %d row(s) could not be matched to home/away "
            "(selection_side=unknown)\n" % unknown
        )
    out.write("written       %s\n" % path)


def main(argv=None):
    args = parse_args(argv)
    key = None if args.demo else pe_nrl.api_key_from_env(required=True)

    with pe_nrl.Client(api_key=key) as client:
        try:
            rows, cost, source = pe_nrl.fetch_rows(
                client, demo=args.demo, markets=args.markets, sport=args.sport
            )
        except pe_nrl.ApiError as exc:
            sys.stderr.write("API error: %s\n" % exc)
            return 1

    if not rows:
        sys.stderr.write(
            "No priced NRL fixtures returned by %s.\n"
            "Out of season or between rounds this is a normal empty result, "
            "not a failure.\n" % source
        )
        # Still write the header so downstream jobs get a valid, empty CSV.
        write_csv(args.out, rows)
        return 0

    if cost is None and args.demo:
        # The demo endpoints send no X-Credits-* headers because they cost nothing.
        cost = "0 (demo endpoint, no key required)"

    write_csv(args.out, rows)
    if not args.quiet:
        summarise(rows, source, cost, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
