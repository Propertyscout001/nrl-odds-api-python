"""Shared helpers for the NRL odds scripts: HTTP, flattening, team-name matching.

Standard library only. Python 3.8+.

The three scripts in this repo (fetch_nrl.py, track.py, analysis.py) all lean on
this module so the CSV schema is defined in exactly one place.
"""

from __future__ import annotations

import gzip
import http.client
import io
import json
import os
import re
import sys
import zlib
from datetime import datetime, timezone

API_HOST = "api.puntersedge.online"
API_PREFIX = "/v1"
USER_AGENT = "nrl-odds-api-python/1.0 (+https://github.com/Propertyscout001/nrl-odds-api-python)"

SIGNUP_URL = (
    "https://puntersedge.online/api"
    "?utm_source=nrl-odds-api-python&utm_medium=code"
)

# The CSV schema. The first nine columns are the "tidy" core; the last four are
# extras this repo adds because they turned out to be necessary (see README).
FIELDNAMES = [
    "event_id",
    "commence_time",
    "home",
    "away",
    "bookmaker",
    "market",
    "selection",
    "selection_side",
    "point",
    "price",
    "book_last_update",
    "book_age_seconds",
    "fetched_at",
]


class ApiError(RuntimeError):
    """An RFC 9457 problem+json response, or a transport failure."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Client:
    """A tiny keep-alive HTTPS client.

    urllib.request opens a fresh TLS connection per call. On this feed a cold
    connection measured a ~198ms median against ~65ms on a reused one (see
    docs/output.txt section 8), so when track.py polls in a loop the handshake
    dominates. http.client lets us hold the socket open, which is the whole
    reason this class exists instead of urlopen().
    """

    def __init__(self, api_key: str = None, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._conn = None

    def _connect(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(API_HOST, timeout=self.timeout)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def get_json(self, path: str, params: dict = None):
        """GET {path} and return parsed JSON. Retries ONCE, and only on a dropped
        connection -- never on an HTTP error. A silent retry after a 5xx can hand
        you a price that was recorded before a move, which is worse than an
        exception."""
        query = _encode_query(params or {})
        url = API_PREFIX + path + (("?" + query) if query else "")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
            "Connection": "keep-alive",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        for attempt in (1, 2):
            conn = self._connect()
            try:
                conn.request("GET", url, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
            except (http.client.HTTPException, OSError) as exc:
                self.close()
                if attempt == 2:
                    raise ApiError("transport error on GET %s: %s" % (url, exc))
                continue

            body = _decompress(raw, resp.getheader("Content-Encoding"))
            self.last_credits_cost = resp.getheader("X-Credits-Cost")
            self.last_credits_remaining = resp.getheader("X-Credits-Remaining")

            if resp.status >= 400:
                raise ApiError(_format_problem(resp.status, body))
            try:
                return json.loads(body)
            except ValueError as exc:
                raise ApiError("GET %s returned non-JSON: %s" % (url, exc))
        raise ApiError("unreachable")


def _encode_query(params: dict) -> str:
    from urllib.parse import urlencode

    clean = {k: v for k, v in params.items() if v is not None}
    return urlencode(clean)


def _decompress(raw: bytes, encoding: str) -> str:
    if not encoding:
        return raw.decode("utf-8", "replace")
    enc = encoding.lower()
    if enc == "gzip":
        return gzip.GzipFile(fileobj=io.BytesIO(raw)).read().decode("utf-8", "replace")
    if enc == "deflate":
        return zlib.decompress(raw).decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


def _format_problem(status: int, body: str) -> str:
    """Errors come back as RFC 9457 problem+json: {type,title,status,detail}."""
    try:
        doc = json.loads(body)
    except ValueError:
        return "HTTP %d: %s" % (status, body[:300])
    if isinstance(doc, dict) and ("title" in doc or "detail" in doc):
        title = (doc.get("title") or "").strip()
        detail = (doc.get("detail") or "").strip()
        # This API often repeats itself across the two fields; say it once.
        if detail and detail != title:
            return "HTTP %d %s: %s" % (status, title, detail)
        return "HTTP %d %s" % (status, detail or title)
    return "HTTP %d: %s" % (status, body[:300])


def api_key_from_env(required: bool = True):
    """Read the key from the environment.

    PUNTERSEDGE_API_KEY is the name every other repo in this estate uses
    (puntersedge-python, -node, -mcp, puntersedge-examples,
    au-racing-odds-dashboard), so it wins. PE_API_KEY is kept as an alias
    because earlier versions of this repo documented it.
    """
    key = (
        os.environ.get("PUNTERSEDGE_API_KEY")
        or os.environ.get("PE_API_KEY")
        or ""
    ).strip()
    if not key and required:
        sys.stderr.write(
            "PUNTERSEDGE_API_KEY is not set (PE_API_KEY is also accepted).\n"
            "  Free key (1,500 credits/month, no card): %s\n"
            "  Or run with --demo for the keyless sample feed.\n" % SIGNUP_URL
        )
        raise SystemExit(2)
    return key or None


# --------------------------------------------------------------------------
# Team-name matching
#
# Bookmakers do not agree on how to spell a club. In one live response on
# 2026-09-15 a single team appeared as "Cronulla", "Cronulla Sharks" and
# "Cronulla-Sutherland Sharks" depending on the book, and the Roosters were
# "Syd Roosters" at one book and "Sydney Roosters" at five others. Outcome
# ORDER is not stable either -- one book listed the away team first.
#
# So a cross-book join cannot use the raw selection string and cannot use
# position. We resolve every outcome to home/away/over/under instead.
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(name: str):
    return [t for t in _TOKEN_RE.findall((name or "").lower()) if len(t) > 1]


def _score(outcome_tokens, team_tokens) -> float:
    """Exact token match scores 1.0; an abbreviation prefix (syd -> sydney)
    scores 0.5. Exact therefore always outranks a prefix coincidence, which is
    what keeps 'Newcastle' on the away side even though 'new' prefixes it."""
    total = 0.0
    for ot in outcome_tokens:
        best = 0.0
        for tt in team_tokens:
            if ot == tt:
                best = max(best, 1.0)
            elif len(ot) >= 3 and len(tt) >= 3 and (tt.startswith(ot) or ot.startswith(tt)):
                best = max(best, 0.5)
        total += best
    return total


def resolve_side(selection: str, home: str, away: str) -> str:
    """Return 'home', 'away', 'draw', 'over', 'under' or 'unknown'.

    'draw' is not decoration. Not every h2h market is two-way: super_league and
    soccer return a third selection, and sportsbet and pointsbetau both sent
    'Draw' on Super League fixtures on 2026-09-15. Code that assumes two
    outcomes per event will mis-handle those.
    """
    flat = (selection or "").strip().lower()
    if flat in ("over", "o"):
        return "over"
    if flat in ("under", "u"):
        return "under"
    if flat.startswith("over "):
        return "over"
    if flat.startswith("under "):
        return "under"
    if flat in ("draw", "the draw", "tie", "x"):
        return "draw"

    ot = _tokens(selection)
    if not ot:
        return "unknown"
    h = _score(ot, _tokens(home))
    a = _score(ot, _tokens(away))
    if h <= 0 and a <= 0:
        return "unknown"
    if abs(h - a) < 0.25:
        return "unknown"
    return "home" if h > a else "away"


# --------------------------------------------------------------------------
# Flattening
# --------------------------------------------------------------------------


def flatten_keyed(events, fetched_at: str):
    """Flatten the bare array returned by GET /v1/sports/nrl/odds.

    Shape: [ {id, home_team, away_team, commence_time,
              bookmakers: [ {key, last_update, age_seconds,
                             markets: [ {key, outcomes: [{name, price, point?}]} ]} ]} ]
    """
    rows = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        home = ev.get("home_team") or ""
        away = ev.get("away_team") or ""
        event_id = ev.get("id") or ""
        commence = ev.get("commence_time") or ""
        for bk in ev.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                for out in mk.get("outcomes") or []:
                    # Built in FIELDNAMES order so list(row.values()) is stable
                    # and matches flatten_demo(). selftest.py asserts this.
                    rows.append(
                        {
                            "event_id": event_id,
                            "commence_time": commence,
                            "home": home,
                            "away": away,
                            "bookmaker": bk.get("key") or "",
                            "market": mk.get("key") or "",
                            "selection": out.get("name") or "",
                            "selection_side": resolve_side(out.get("name"), home, away),
                            "point": _num(out.get("point")),
                            "price": _num(out.get("price")),
                            "book_last_update": bk.get("last_update") or "",
                            "book_age_seconds": _num(bk.get("age_seconds")),
                            "fetched_at": fetched_at,
                        }
                    )
    return rows


def flatten_demo(payload, fetched_at: str):
    """Flatten GET /v1/demo/best-odds?sport=nrl.

    The demo endpoint returns an ENVELOPE, not a bare array:
      {"demo":true, "note":..., "sport":"nrl", "events":[...]}
    and each event carries only the BEST price per selection, not every book's
    price, and no event id. We synthesise a stable id so the CSV still joins.
    The envelope also carries arb_* fields; this repo ignores them.
    """
    events = payload.get("events") if isinstance(payload, dict) else payload
    rows = []
    for ev in events or []:
        home = ev.get("home_team") or ""
        away = ev.get("away_team") or ""
        commence = ev.get("commence_time") or ""
        eid = "demo-" + _stable_id(home, away, commence)
        for sel in ev.get("selections") or []:
            rows.append(
                {
                    "event_id": eid,
                    "commence_time": commence,
                    "home": home,
                    "away": away,
                    "bookmaker": sel.get("best_bookmaker") or "",
                    "market": "h2h",
                    "selection": sel.get("name") or "",
                    "selection_side": resolve_side(sel.get("name"), home, away),
                    "point": "",
                    "price": _num(sel.get("best_price")),
                    "book_last_update": "",
                    "book_age_seconds": "",
                    "fetched_at": fetched_at,
                }
            )
    return rows


def _stable_id(*parts) -> str:
    import hashlib

    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _num(value):
    if value is None:
        return ""
    return value


def fetch_rows(client: Client, demo: bool, markets: str = "h2h", sport: str = "nrl"):
    """Return (rows, credit_cost_header, source_label)."""
    fetched_at = utc_now_iso()
    if demo:
        payload = client.get_json("/demo/best-odds", {"sport": sport})
        return (
            flatten_demo(payload, fetched_at),
            client.last_credits_cost,
            "/v1/demo/best-odds?sport=%s" % sport,
        )
    payload = client.get_json("/sports/%s/odds" % sport, {"markets": markets})
    return (
        flatten_keyed(payload, fetched_at),
        client.last_credits_cost,
        "/v1/sports/%s/odds?markets=%s" % (sport, markets),
    )
