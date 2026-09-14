#!/usr/bin/env python3
"""Append-only snapshotting: repeated runs build a local NRL price history.

    python3 track.py --demo                       # one keyless snapshot
    python3 track.py                              # one keyed snapshot (1 credit)
    python3 track.py --interval 300 --count 12    # 12 snapshots, 5 min apart
    python3 track.py --summary                    # what's in the history file

Every run APPENDS to data/nrl_history.csv. Nothing is ever rewritten, so the
file is a log, not a state table: the same (event, bookmaker, market, selection)
key appears once per snapshot and the price column is what that book was showing
at that moment.


Why snapshot instead of trusting one fetch
------------------------------------------
Two reasons, both measurable in the feed itself.

1. A single response is not a single instant. Each bookmaker block carries its
   own `age_seconds`. In one live response captured 2026-09-15, sportsbet's
   NRL market was 2200 seconds old while tab's was 147 seconds old -- both in
   the same JSON body. Treating those two prices as simultaneous observations
   is a modelling error. The CSV keeps `book_last_update` and
   `book_age_seconds` per row so you can filter on observation age rather than
   on when your script happened to run.

2. Prices move and the API does not keep your history for you. The hosted
   /v1/sports/nrl/odds/movements endpoint costs 5 credits per call, covers h2h
   only and defaults to a 24-hour window. A local snapshot log costs 1 credit
   per call, covers every market you asked for, and is yours to keep for as
   long as you run it. Use the hosted endpoint to backfill what you missed;
   use this to build forward.

The obvious failure mode is a gap: if your snapshotter is down, the history has
a hole and nothing in the file tells you the hole is there. `--summary` prints
the gap between consecutive snapshots so you can see it.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import OrderedDict

import pe_nrl

DEFAULT_HISTORY = "data/nrl_history.csv"

# What makes one tracked price series. Note that `point` is part of the key:
# a single bookmaker can return more than one line inside the same market
# (tab returned totals at both 45.5 and 7.5 in one response), so
# (event, book, market, side) alone is NOT unique.
KEY_FIELDS = ("event_id", "bookmaker", "market", "selection_side", "point")


def row_key(row):
    return tuple(str(row.get(f, "")) for f in KEY_FIELDS)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Append NRL odds snapshots to a local history CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Free API key (1,500 credits/month, no card): " + pe_nrl.SIGNUP_URL,
    )
    p.add_argument("--demo", action="store_true", help="keyless demo feed (0 credits)")
    p.add_argument("--sport", default="nrl", help="nrl (default), nrlw, super_league")
    p.add_argument("--markets", default="h2h", help="h2h,spreads,totals")
    p.add_argument(
        "--history", default=DEFAULT_HISTORY, help="history CSV (default: %s)" % DEFAULT_HISTORY
    )
    p.add_argument("--interval", type=float, default=0.0, help="seconds between snapshots")
    p.add_argument("--count", type=int, default=1, help="number of snapshots to take")
    p.add_argument("--summary", action="store_true", help="describe the history file and exit")
    p.add_argument(
        "--movements",
        action="store_true",
        help="print the HOSTED change feed instead of snapshotting (5 credits, h2h only)",
    )
    p.add_argument("--since", default=None, help="ISO date/time for --movements (default: 24h ago)")
    return p.parse_args(argv)


def load_last_prices(path):
    """Last seen price per key, plus every distinct snapshot timestamp."""
    last = {}
    snapshots = OrderedDict()
    if not os.path.exists(path):
        return last, list(snapshots)
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            last[row_key(row)] = row.get("price", "")
            snapshots[row.get("fetched_at", "")] = True
    return last, list(snapshots)


def append_rows(path, rows):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=pe_nrl.FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def describe(path):
    if not os.path.exists(path):
        print("No history file at %s yet. Run: python3 track.py --demo" % path)
        return 1
    rows = 0
    keys = set()
    snaps = OrderedDict()
    changes = 0
    last = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows += 1
            k = row_key(row)
            keys.add(k)
            snaps[row.get("fetched_at", "")] = True
            price = row.get("price", "")
            if k in last and last[k] != price:
                changes += 1
            last[k] = price

    stamps = [s for s in snaps if s]
    print("history file    %s" % path)
    print("rows            %d" % rows)
    print("snapshots       %d" % len(stamps))
    print("price series    %d  (distinct %s)" % (len(keys), "+".join(KEY_FIELDS)))
    print("price changes   %d observed between consecutive snapshots" % changes)
    if stamps:
        print("first snapshot  %s" % stamps[0])
        print("last snapshot   %s" % stamps[-1])
    if len(stamps) > 1:
        gaps = _gaps(stamps)
        if gaps:
            print(
                "snapshot gaps   min %ds / median %ds / max %ds  "
                "(a large max means the tracker was not running)"
                % (min(gaps), sorted(gaps)[len(gaps) // 2], max(gaps))
            )
    return 0


def _gaps(stamps):
    from datetime import datetime

    out = []
    prev = None
    for s in stamps:
        try:
            cur = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        if prev is not None:
            out.append(int((cur - prev).total_seconds()))
        prev = cur
    return out


def show_movements(client, args):
    """Print /v1/sports/{sport}/odds/movements -- the hosted change feed.

    This is the backfill half of the story. It costs 5 credits, covers h2h only
    and defaults to a 24-hour window, but it tells you what moved while your
    snapshotter was not running. The payload gives raw deltas, not direction
    words; 'firming' / 'drifting' below are this script's labels for a decimal
    price that went down / up.
    """
    rows = client.get_json(
        "/sports/%s/odds/movements" % args.sport,
        {"since": args.since, "market": "h2h"},
    )
    print(
        "hosted change feed  /v1/sports/%s/odds/movements  (cost %s credits)"
        % (args.sport, client.last_credits_cost or "5")
    )
    print("window              %s" % (args.since or "last 24 hours (API default)"))
    print("changes returned    %d\n" % len(rows or []))
    if not rows:
        print("Nothing moved in the window.")
        return 0

    for r in rows:
        print(
            "%s vs %s  --  %s"
            % (r.get("home_team"), r.get("away_team"), r.get("bookmaker"))
        )
        print(
            "  %s -> %s"
            % (r.get("from_recorded_at", "?")[:19], r.get("to_recorded_at", "?")[:19])
        )
        for field, change in sorted((r.get("changes") or {}).items()):
            try:
                delta = float(change.get("delta"))
                direction = "firming" if delta < 0 else "drifting"
            except (TypeError, ValueError):
                delta, direction = 0.0, "changed"
            print(
                "    %-12s %s -> %s  (%+.2f, %s)"
                % (field, change.get("from"), change.get("to"), delta, direction)
            )
        print()
    return 0


def snapshot(client, args, last_prices):
    rows, cost, source = pe_nrl.fetch_rows(
        client, demo=args.demo, markets=args.markets, sport=args.sport
    )
    if not rows:
        print("  no priced fixtures returned -- nothing appended")
        return last_prices, 0

    had_prior = bool(last_prices)
    moved = []
    for row in rows:
        k = row_key(row)
        prev = last_prices.get(k)
        cur = str(row.get("price", ""))
        if prev is not None and str(prev) != cur:
            moved.append((row, prev, cur))
        last_prices[k] = cur

    append_rows(args.history, rows)

    stamp = rows[0]["fetched_at"]
    print(
        "  %s  +%d rows  (%s, cost %s)"
        % (stamp, len(rows), source, cost if cost is not None else "0")
    )
    for row, prev, cur in moved:
        try:
            direction = "firming" if float(cur) < float(prev) else "drifting"
        except (TypeError, ValueError):
            direction = "changed"
        line = (" @%s" % row["point"]) if row["point"] not in ("", None) else ""
        print(
            "    %-13s %-7s %-6s%-7s %s -> %s  (%s)"
            % (
                row["bookmaker"],
                row["market"],
                row["selection_side"],
                line,
                prev,
                cur,
                direction,
            )
        )
    if not moved:
        print(
            "    no price changes since the previous snapshot"
            if had_prior
            else "    first snapshot -- baseline recorded, nothing to compare against yet"
        )
    sys.stdout.flush()  # so a long --interval run is not silent when redirected
    return last_prices, len(moved)


def main(argv=None):
    args = parse_args(argv)
    if args.summary:
        return describe(args.history)

    key = None if args.demo else pe_nrl.api_key_from_env(required=True)

    if args.movements:
        with pe_nrl.Client(api_key=key) as client:
            try:
                return show_movements(client, args)
            except pe_nrl.ApiError as exc:
                sys.stderr.write("API error: %s\n" % exc)
                return 1

    last_prices, _ = load_last_prices(args.history)
    total_moves = 0

    with pe_nrl.Client(api_key=key) as client:
        for i in range(max(1, args.count)):
            print("snapshot %d/%d" % (i + 1, max(1, args.count)))
            try:
                last_prices, moved = snapshot(client, args, last_prices)
                total_moves += moved
            except pe_nrl.ApiError as exc:
                # Do not swallow this. A failed snapshot is a hole in the
                # history and you want to know about it.
                sys.stderr.write("  API error: %s\n" % exc)
                return 1
            if i + 1 < max(1, args.count) and args.interval > 0:
                time.sleep(args.interval)

    print("\n%d price change(s) recorded this run. Appended to %s" % (total_moves, args.history))
    print("Inspect with: python3 track.py --summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
