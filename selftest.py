#!/usr/bin/env python3
"""Offline checks for the parts that are easy to get quietly wrong.

    python3 selftest.py

No network, no API key, no pytest (the target machine has none). Exit code 0
means every case passed.

The team-name cases below are not invented -- they are the exact strings six
Australian bookmakers returned for two NRL fixtures in one live response on
2026-09-15. See docs/output.txt.
"""

from __future__ import annotations

import sys

import pe_nrl
from pe_nrl import flatten_demo, flatten_keyed, resolve_side

FAILURES = []


def check(label, got, expected):
    if got != expected:
        FAILURES.append("%s: got %r, expected %r" % (label, got, expected))
        print("FAIL  %s -> %r (expected %r)" % (label, got, expected))
    else:
        print("ok    %s -> %r" % (label, got))


def test_side_resolution():
    print("-- team-name matching (real strings from six books) --")
    roosters = ("Syd Roosters", "Cronulla")
    for name, expected in [
        ("Sydney Roosters", "home"),      # betright, ladbrokes_au, palmerbet, sportsbet
        ("Syd Roosters", "home"),          # tab, and the event-level home_team
        ("Cronulla-Sutherland Sharks", "away"),  # betright, pointsbetau
        ("Cronulla Sharks", "away"),       # ladbrokes_au, palmerbet, sportsbet
        ("Cronulla", "away"),              # tab
    ]:
        check(name, resolve_side(name, *roosters), expected)

    warriors = ("New Zealand Warriors", "Newcastle Knights")
    for name, expected in [
        ("New Zealand Warriors", "home"),
        ("Warriors", "home"),              # tab
        ("Newcastle Knights", "away"),
        ("Newcastle", "away"),             # tab -- 'new' prefixes it, must not win
    ]:
        check(name, resolve_side(name, *warriors), expected)

    print("-- totals, three-way markets, and unmatchable --")
    check("Over", resolve_side("Over", *roosters), "over")
    check("Under", resolve_side("Under", *roosters), "under")
    # Not every h2h market is two-way. sportsbet and pointsbetau both returned
    # 'Draw' on Super League fixtures; NRL itself did not.
    check("Draw", resolve_side("Draw", *roosters), "draw")
    check("The Draw", resolve_side("The Draw", *roosters), "draw")
    check("empty", resolve_side("", *roosters), "unknown")
    check("nonsense", resolve_side("Manly Sea Eagles", *roosters), "unknown")


def test_keyed_shape():
    """The keyed endpoint returns a BARE ARRAY.

    The two totals lines below (45.5 and 7.5 from one book, in one market) are
    not invented for the test -- tab really does send both for the same fixture.
    See docs/output.txt section 3 for the awk over live data that shows it. That
    is why `point` is part of track.py's series key. The age_seconds value is a
    fixture constant and is not a measurement of anything.
    """
    print("-- flatten_keyed (bare array) --")
    payload = [
        {
            "id": "abc",
            "home_team": "Syd Roosters",
            "away_team": "Cronulla",
            "commence_time": "2026-09-19T09:30:00Z",
            "bookmakers": [
                {
                    "key": "tab",
                    "last_update": "2026-09-14T23:14:48.124289",
                    "age_seconds": 147,
                    "markets": [
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "point": 45.5, "price": 1.9},
                                {"name": "Over", "point": 7.5, "price": 1.65},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    rows = flatten_keyed(payload, "2026-09-15T00:00:00Z")
    check("row count", len(rows), 2)
    check("point is kept", sorted(r["point"] for r in rows), [7.5, 45.5])
    check("side", {r["selection_side"] for r in rows}, {"over"})
    check("age carried through", rows[0]["book_age_seconds"], 147)
    check("columns", list(rows[0].keys()) == pe_nrl.FIELDNAMES, True)


def test_demo_shape():
    """The demo endpoint returns an ENVELOPE, not a bare array."""
    print("-- flatten_demo (envelope) --")
    payload = {
        "demo": True,
        "note": "Free sandbox sample (truncated).",
        "events": [
            {
                "home_team": "Warriors",
                "away_team": "Newcastle",
                "commence_time": "2026-09-18T09:00:00Z",
                "selections": [
                    {"name": "Warriors", "best_price": 1.5, "best_bookmaker": "betright"},
                    {"name": "Newcastle", "best_price": 2.7, "best_bookmaker": "tab"},
                ],
                "arb_exists": False,
            }
        ],
    }
    rows = flatten_demo(payload, "2026-09-15T00:00:00Z")
    check("row count", len(rows), 2)
    check("synthetic id is stable", rows[0]["event_id"], rows[1]["event_id"])
    check("id is marked demo", rows[0]["event_id"].startswith("demo-"), True)
    check("sides resolved", [r["selection_side"] for r in rows], ["home", "away"])
    check("columns", list(rows[0].keys()) == pe_nrl.FIELDNAMES, True)
    # A bare array must not be mistaken for an envelope, and vice versa.
    check("envelope != bare array", flatten_keyed(payload.get("events"), "x"), [])


def test_error_formatting():
    print("-- RFC 9457 problem+json --")
    msg = pe_nrl._format_problem(
        403,
        '{"type":"about:blank","title":"Forbidden",'
        '"status":403,"detail":"closing-lines requires a paid plan"}',
    )
    check("problem json parsed", "closing-lines requires a paid plan" in msg, True)
    check("non-json tolerated", pe_nrl._format_problem(502, "<html>bad gateway</html>")[:8], "HTTP 502")


def main():
    test_side_resolution()
    print()
    test_keyed_shape()
    print()
    test_demo_shape()
    print()
    test_error_formatting()
    print()
    if FAILURES:
        print("%d FAILURE(S):" % len(FAILURES))
        for f in FAILURES:
            print("  " + f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
