<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
  <img alt="PuntersEdge API" src="docs/logo-light.svg" width="400">
</picture>

# NRL odds API in Python

Three small Python scripts that read NRL prices from an Australian odds API and
turn them into something a model can consume: a long-format CSV, an append-only
price history, and a report on how far apart the bookmakers are.

This is written for someone building a **feed**, not a viewer. There is no
dashboard and no UI. The output is a CSV with one row per
`(fixture, bookmaker, market, selection)` that you point pandas, DuckDB or a
database loader at.

Data comes from the [PuntersEdge](https://puntersedge.online/api?utm_source=nrl-odds-api-python&utm_medium=readme)
API — Australian bookmaker prices for NRL, NRLW and Super League, plus the other
sports and AU/NZ racing. Everything here is standard library only: no pip
install, no virtualenv, works on a stock `python3`.

## Run it without an API key

```bash
git clone https://github.com/Propertyscout001/nrl-odds-api-python.git
cd nrl-odds-api-python
python3 fetch_nrl.py --demo -o data/demo_odds.csv && python3 analysis.py data/demo_odds.csv
```

That hits `GET /v1/demo/best-odds?sport=nrl`, which needs no key and costs no
credits. Real output, captured 2026-09-15 AEST — the API returns UTC, which is
why the timestamps inside the output read `2026-09-15T00:…`:

```
$ python3 fetch_nrl.py --demo -o data/demo_odds.csv
source        /v1/demo/best-odds?sport=nrl
credit cost   0 (demo endpoint, no key required)
rows          6
fixtures      3
bookmakers    5 (betright, ladbrokes_au, palmerbet, sportsbet, tab)
markets       h2h=6
written       data/demo_odds.csv

$ head -4 data/demo_odds.csv
event_id,commence_time,home,away,bookmaker,market,selection,selection_side,point,price,book_last_update,book_age_seconds,fetched_at
demo-817965461287,2026-09-16T02:00:00Z,New Zealand Warriors,Newcastle Knights,palmerbet,h2h,New Zealand Warriors,home,,1.48,,,2026-09-15T00:06:44Z
demo-817965461287,2026-09-16T02:00:00Z,New Zealand Warriors,Newcastle Knights,sportsbet,h2h,Newcastle Knights,away,,2.76,,,2026-09-15T00:06:44Z
demo-0564ae638f8b,2026-09-18T09:00:00Z,Warriors,Newcastle,betright,h2h,Warriors,home,,1.5,,,2026-09-15T00:06:44Z
```

The demo feed is a truncated sample that returns only the **best** price per
selection, not each book's price — so there is no dispersion in it to measure,
and `analysis.py` says so rather than printing a misleading zero:

```
$ python3 analysis.py data/demo_odds.csv
source        data/demo_odds.csv
market        h2h
comparisons   0 of 6 selection(s) priced by >= 2 book(s), across 3 fixture(s)
skipped       6 selection(s) priced by only one book

Nothing to compare: every selection in this file carries a price from a
single bookmaker only.

That is the expected result for a --demo CSV. The keyless demo endpoint
returns the BEST price per selection, not each book's price, so there is
no dispersion in it to measure. Fetch with an API key to compare books:
  export PUNTERSEDGE_API_KEY=...
  python3 fetch_nrl.py --markets h2h -o data/nrl_odds.csv
  python3 analysis.py data/nrl_odds.csv

Free key (1,500 credits/month, no card):
  https://puntersedge.online/api?utm_source=nrl-odds-api-python&utm_medium=code
```

To compare books you need every book's price, which needs a key.

## With a free key

A free key is 1,500 credits a month, no credit card:
**[puntersedge.online/api](https://puntersedge.online/api?utm_source=nrl-odds-api-python&utm_medium=readme)**.

The scripts read `PUNTERSEDGE_API_KEY` — the same variable the
[PuntersEdge SDKs](https://github.com/Propertyscout001/puntersedge-python) use, so
if you already have one exported it just works. `PE_API_KEY` is accepted as an
alias.

```bash
export PUNTERSEDGE_API_KEY="pe_live_..."
python3 fetch_nrl.py --markets h2h,spreads,totals -o data/nrl_odds.csv
python3 analysis.py data/nrl_odds.csv --market h2h
```

Real output, captured 2026-09-15 (six books, two fixtures):

```
$ python3 fetch_nrl.py --markets h2h,spreads,totals -o data/nrl_odds.csv
source        /v1/sports/nrl/odds?markets=h2h,spreads,totals
credit cost   3
rows          52
fixtures      2
bookmakers    6 (betright, ladbrokes_au, palmerbet, pointsbetau, sportsbet, tab)
markets       h2h=24, spreads=12, totals=16
written       data/nrl_odds.csv

$ python3 analysis.py data/nrl_odds.csv --market h2h
source        data/nrl_odds.csv
market        h2h
comparisons   4 of 4 selection(s) priced by >= 2 book(s), across 2 fixture(s)

Syd Roosters  vs  Cronulla
  kicks off 2026-09-19T09:30:00Z
  market   line   side       best book             worst book           spread% oldest
  h2h      -      away      3.000 ladbrokes_au     2.750 tab              9.09%     6m
  h2h      -      home      1.450 tab              1.400 ladbrokes_au     3.57%     6m

New Zealand Warriors  vs  Newcastle Knights
  kicks off 2026-09-20T06:05:00Z
  market   line   side       best book             worst book           spread% oldest
  h2h      -      away      2.750 pointsbetau      2.550 tab              7.84%     6m
  h2h      -      home      1.520 tab              1.440 pointsbetau      5.56%     6m

Widest disagreement: 9.09% on the h2h away selection (Syd Roosters vs Cronulla, 6 books).
...
```

(The `...` is a three-line explainer about the `oldest` column. The
[full captured session](docs/output.txt) has every command in this README
untrimmed, including the spreads and totals reports and a live `track.py` run.)

### Credit cost per run

| Script | Endpoint | Credits |
| --- | --- | --- |
| `fetch_nrl.py --demo` | `/v1/demo/best-odds?sport=nrl` | 0 |
| `fetch_nrl.py` | `/v1/sports/nrl/odds` | 1 per market (so `h2h,spreads,totals` = 3) |
| `track.py` | same as above, once per snapshot | 1 per market, per snapshot |
| `track.py --movements` | `/v1/sports/nrl/odds/movements` | 5 |
| `analysis.py` | none — reads your CSV | 0 |
| `selftest.py` | none — offline | 0 |

`/v1/best-odds/nrl` (3 credits) returns the best price per selection with every
book's price nested underneath. It is not used by these scripts — see
[How it works](#how-it-works) for why.

Every response carries `X-Credits-Used` and `X-Credits-Remaining`; `fetch_nrl.py`
prints the `X-Credits-Cost` of the call it just made.

## The three scripts

### `fetch_nrl.py` — fixtures and prices to a tidy CSV

One row per price. Columns:

| Column | Notes |
| --- | --- |
| `event_id` | API event UUID. Synthesised as `demo-<hash>` in `--demo` mode, which returns no id. |
| `commence_time` | UTC ISO 8601. |
| `home`, `away` | Event-level team names. **Not** the same strings the books use. |
| `bookmaker` | `tab`, `sportsbet`, `ladbrokes_au`, … |
| `market` | `h2h`, `spreads`, `totals`. |
| `selection` | The book's own spelling, unmodified. |
| `selection_side` | `home` / `away` / `draw` / `over` / `under` / `unknown`. **This is the join key.** |
| `point` | The line, for spreads and totals. Empty for h2h. |
| `price` | Decimal odds. |
| `book_last_update` | When that book's market was last refreshed upstream. |
| `book_age_seconds` | How stale that quote was when the API served it. |
| `fetched_at` | When *your* script made the request. Deliberately separate from the two above. |

The first nine are the tidy core. The last four exist because leaving them out
produced a CSV that quietly lied about when a price was observed.

Because `selection_side` is consistent across books, a cross-book matrix is one
call — this is the whole point of the column:

```python
import pandas as pd
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", None)
df = pd.read_csv("data/nrl_odds.csv")
h2h = df[df.market == "h2h"]
print(h2h.pivot_table(index=["event_id", "selection_side"],
                      columns="bookmaker", values="price"))
```

Real output, 2026-09-15 (pandas 2.3.3):

```
bookmaker                                            betright  ladbrokes_au  palmerbet  pointsbetau  sportsbet   tab
event_id                             selection_side
b8ed83fd-52e1-4449-a8f6-9cd0f1ef593a away                2.58          2.70       2.57         2.75       2.57  2.55
                                     home                1.51          1.48       1.51         1.44       1.51  1.52
f1562698-93f1-446c-bc51-0ca26288c689 away                2.80          3.00       2.82         2.80       2.82  2.75
                                     home                1.44          1.40       1.44         1.42       1.44  1.45
```

Pivoting on the raw `selection` column instead would split those four real
selections across the **nine** distinct strings the six books used for them —
`awk -F, '$6=="h2h"{print $7}' data/nrl_odds.csv | sort -u | wc -l` printed `9`
in the captured session. (pandas is not required by the scripts themselves —
they are stdlib only.)

Also takes `--sport nrlw` and `--sport super_league`.

### `track.py` — append-only snapshots

```bash
python3 track.py --markets h2h --interval 300 --count 12   # 12 snapshots, 5 min apart
python3 track.py --summary                                 # what's in the file
python3 track.py --movements                               # hosted change feed (5 credits)
```

Each run appends to `data/nrl_history.csv` and prints what moved since the
previous snapshot. Nothing is rewritten, so the file is a log rather than a
state table, and re-running it is always safe.

`--count > 1` requires an `--interval`. These scripts have no rate-limit backoff
(see Limitations), so a back-to-back burst would just trip the per-minute limit
and die at snapshot 1. The script refuses it up front rather than letting you
find out:

```
$ python3 track.py --count 12
refusing to burst 12 requests with --interval 0: the API has a per-minute limit
and this script does not back off. Pass --interval (e.g. --interval 60).
(exit 2)
```

**Why snapshot instead of trusting a single fetch.** Two reasons, both visible
in the feed itself:

1. *One response is not one instant.* Every bookmaker block carries its own
   `age_seconds`. In the response in [docs/output.txt](docs/output.txt), five
   books were 155–166 seconds old while sportsbet's quote was **395 seconds**
   old — all in the same JSON body. Those are not simultaneous observations,
   and a model that treats them as such is wrong in a way that never surfaces
   as an error. That is what `book_age_seconds` is for:

   ```
   $ awk -F, 'NR>1{print $5, $12"s"}' data/nrl_odds.csv | sort -u
   betright 166s
   ladbrokes_au 166s
   palmerbet 155s
   pointsbetau 164s
   sportsbet 395s
   tab 166s
   ```

   The size of that gap moves around. Across the capture runs for this README
   sportsbet came back 256s, 383s, 728s and 395s stale while every other book
   sat inside a couple of minutes; only the last of those is the one committed
   to `docs/output.txt`.
2. *The API does not keep your history for you.* The hosted
   `/v1/sports/nrl/odds/movements` endpoint costs 5 credits, covers `h2h` only
   and defaults to a 24-hour window. A local snapshot costs 1 credit and keeps
   every market you asked for, for as long as you run it. Use the hosted
   endpoint to backfill; use this to build forward.

The obvious failure mode is a gap — if the snapshotter is down, the history has
a hole and nothing in the file announces it. `--summary` prints the gap between
consecutive snapshots so you can see one:

```
$ python3 track.py --summary
history file    data/nrl_history.csv
rows            312
snapshots       6
price series    52  (distinct event_id+bookmaker+market+selection_side+point)
price changes   0 observed between consecutive snapshots
first snapshot  2026-09-15T00:06:45Z
last snapshot   2026-09-15T00:11:46Z
snapshot gaps   min 60s / median 60s / max 61s  (a large max means the tracker was not running)
```

Six snapshots, five minutes, **zero** price changes — and that is the honest
result, not a broken script. NRL fixtures four days out do not move every
minute. `track.py --movements` calls the hosted change feed (5 credits, h2h
only) and shows the timescale they actually move on:

```
$ python3 track.py --movements
hosted change feed  /v1/sports/nrl/odds/movements  (cost 5 credits)
window              last 24 hours (API default)
changes returned    15

New Zealand Warriors vs Newcastle Knights  --  betright
  2026-09-14T22:12:38 -> 2026-09-14T22:22:47
    away_price   2.72 -> 2.58  (-0.14, firming)
    home_price   1.46 -> 1.51  (+0.05, drifting)
...
```

Fifteen changes in 24 hours, none in my five-minute window. Run the snapshotter
on match day, or on an hourly cron through the week — not in a tight loop. (The
movements payload returns raw deltas; `firming` / `drifting` are this script's
labels for a decimal price that went down / up.)

### `analysis.py` — how far apart are the books

Reads the CSV with stdlib `csv` — no pandas — and for every
`(fixture, market, line, selection)` prints the highest and lowest price across
the books that priced it, plus

```
spread % = (max_price / min_price - 1) * 100
```

It groups by `point`, not just by market. Comparing a −6.5 spread price at one
book against a −7.5 at another is comparing two different bets. On the captured
data that was not hypothetical: of the three books quoting spreads, sportsbet
was on −6.5 while tab and pointsbetau were on −7.5 for the same fixture, and on
the other fixture the split went the other way.

The `oldest` column is the age of the stalest quote in each comparison. A wide
spread is at least as likely to mean one book is slow to update as it is to mean
anything else, and there is no way to tell those apart without the age.

Prices print at three decimal places, not two. At two, a 1.4444 and a 1.4400
both render as `1.44` while the spread column correctly reports 0.31%, and the
row reads like a bug in the tool. Three digits make the row explain itself —
see the Super League output below. When every book lands on the same price the
worst-book column says `N books tied` rather than naming the same book twice.

### `selftest.py` — offline checks

```bash
python3 selftest.py     # no network, no key, no pytest
```

Covers the team-name matcher against the real strings six books returned, both
response shapes, and the error formatter.

## How it works

**Endpoints.** `GET /v1/sports/nrl/odds?markets=…` for the keyed path and
`GET /v1/demo/best-odds?sport=nrl` for the keyless one. Base URL is
`https://api.puntersedge.online/v1`, auth is the `X-API-Key` header. The full
surface is browsable at [api.puntersedge.online/docs](https://api.puntersedge.online/docs)
and the spec is at [openapi.json](https://api.puntersedge.online/openapi.json).

**Bookmakers do not agree on team names.** This is the detail the whole CSV
schema is built around. In one live response on 2026-09-15, six books used
**nine** distinct strings for the four selections in two fixtures — one club
appeared three different ways:

| Book | h2h selection strings |
| --- | --- |
| tab | `Syd Roosters`, `Cronulla` |
| ladbrokes_au, palmerbet, sportsbet | `Sydney Roosters`, `Cronulla Sharks` |
| betright, pointsbetau | `Sydney Roosters`, `Cronulla-Sutherland Sharks` |

and the event-level `home_team` / `away_team` were `Syd Roosters` / `Cronulla`,
matching only one of them. **Outcome order is not stable either** — one book
listed the away team first. So a cross-book join can use neither the raw
selection string nor the array position. `pe_nrl.resolve_side()` scores each
outcome's tokens against the event's home and away names (exact token match 1.0,
abbreviation prefix 0.5, so `Newcastle` stays on the away side even though `new`
prefixes it) and writes the result to `selection_side`. Unmatched rows are
marked `unknown` and counted in the summary rather than silently dropped.

**One bookmaker can return several lines inside one market.** In the captured
response tab returned totals at **both 45.5 and 7.5** for the same fixture —
four outcomes in one totals block — while every other book sent only the one
line. So `(event, book, market, selection)` is *not* unique; `point` has to be
part of any key you build, and `track.py` includes it in its change-detection
key for that reason:

```
$ awk -F, '$6=="totals"{print $5"\t"$9}' data/nrl_odds.csv | sort -u
pointsbetau	44.5
pointsbetau	45.5
sportsbet	44.5
sportsbet	45.5
tab	44.5
tab	45.5
tab	7.5

$ awk -F, '$5=="tab" && $6=="totals"{print $3" vs "$4"\t"$9"\t"$8"\t"$10}' data/nrl_odds.csv | sort
New Zealand Warriors vs Newcastle Knights	44.5	over	1.9
New Zealand Warriors vs Newcastle Knights	44.5	under	1.9
New Zealand Warriors vs Newcastle Knights	7.5	over	1.68
New Zealand Warriors vs Newcastle Knights	7.5	under	2.05
Syd Roosters vs Cronulla	45.5	over	1.9
Syd Roosters vs Cronulla	45.5	under	1.9
Syd Roosters vs Cronulla	7.5	over	1.65
Syd Roosters vs Cronulla	7.5	under	2.1
```

Note that `analysis.py` will not show you this on its own: tab is the only book
on the 7.5 line, so those rows fall under the `--min-books 2` floor and land in
the `skipped 4 selection(s) priced by only one book` count. The awk above is how
you see it.

**Not every head-to-head market is two-way.** NRL has no draw selection, so
this only bites when you reuse the code on another sport — but `--sport
super_league` returns a third h2h outcome and both sportsbet and pointsbetau
priced it. The first version of this repo left those rows as `unknown`;
`selection_side` now has a `draw` value. If you assume two outcomes per event,
`super_league` and `soccer_*` will break that assumption:

```
$ python3 analysis.py data/super_league.csv --market h2h
source        data/super_league.csv
market        h2h
comparisons   6 of 6 selection(s) priced by >= 2 book(s), across 2 fixture(s)

Wakefield Trinity Wildcats  vs  Leigh Leopards
  kicks off 2026-09-18T19:00:00Z
  market   line   side       best book             worst book           spread% oldest
  h2h      -      away      2.500 sportsbet        2.380 ladbrokes_au     5.04%    11m
  h2h      -      draw     17.000 pointsbetau     17.000 2 books tied     0.00%    11m
  h2h      -      home      1.571 pointsbetau      1.530 ladbrokes_au     2.71%    11m

Warrington Wolves  vs  Hull Kingston Rovers
  kicks off 2026-09-19T16:30:00Z
  market   line   side       best book             worst book           spread% oldest
  h2h      -      away      2.850 sportsbet        2.750 pointsbetau      3.64%    11m
  h2h      -      draw     18.000 sportsbet       17.000 pointsbetau      5.88%    11m
  h2h      -      home      1.444 pointsbetau      1.440 sportsbet        0.31%    11m

Widest disagreement: 5.88% on the h2h draw selection (Warrington Wolves vs Hull Kingston Rovers, 2 books).
...
```

That last home row is the three-decimal-places argument in one line: at two
decimals it reads `1.44` versus `1.44` with a 0.31% gap, which looks broken.

**The demo endpoint returns an envelope, the keyed one a bare array.** Demo
gives `{"demo":…, "note":…, "events":[…]}`; the keyed endpoint gives `[…]`
directly. They also carry different fields — demo has `best_price` /
`best_bookmaker` per selection and no event id, the keyed endpoint has a nested
`bookmakers → markets → outcomes` tree. `pe_nrl.py` has a separate flattener for
each rather than one function guessing. The demo envelope also carries `arb_*`
fields; these scripts ignore them.

**gzip and connection reuse.** Measured against this feed on 2026-09-15:

- `Accept-Encoding: gzip` took the `h2h,spreads,totals` payload from 9,613
  bytes to 1,167 on the wire — 8.2×. `urllib` and `http.client` do **not** send
  that header for you, so `pe_nrl.Client` sets it and decompresses manually.
- A cold TLS handshake measured a **197.5 ms** median against **65 ms** on a
  reused connection (6 requests each, same endpoint, same minute; the warm
  series is measured after one uncounted priming request, since that request is
  the one that pays the handshake). That is why `pe_nrl.Client` wraps a
  persistent `http.client.HTTPSConnection` instead of calling `urlopen` per
  request — it matters as soon as `track.py` polls in a loop.

Both measurements are reproduced at the end of
[docs/output.txt](docs/output.txt). They are a handful of samples over one
residential connection on one morning, not a benchmark — the ratio is the point,
not the absolute milliseconds.

**Retries.** `Client.get_json` retries once on a dropped connection and **never**
on an HTTP error status. A silent retry after a 5xx on a price endpoint can hand
you a quote recorded before a move, which is worse than an exception. Errors are
RFC 9457 `problem+json` and are surfaced with their `title` and `detail` intact.

**Why not `/v1/best-odds/nrl`.** It costs 3 credits instead of 1, and if the
best price is all you want it is the better call — it hands you the winner per
selection with every book's price nested under `all_prices`. It takes no
`markets` parameter, though, and returned head-to-head selections only in this
build, whereas this repo wants spreads and totals in the same tidy table.

## Limitations

- **No results, no settlement, no outcomes.** Nothing here tells you what
  happened in a match. These scripts read prices and stop.
- **NRL is a small slice.** Out of season, between rounds, or mid-week you will
  get very few fixtures or none at all. Every captured run returned two keyed
  fixtures, because that is what was open at the time.
- **Bookmaker coverage varies by sport, market and fixture.** In the run
  captured for this README, six books priced NRL head-to-head and only three
  priced spreads and totals. The API serves more books than that across its
  whole surface, but note that the published
  [live coverage report](https://puntersedge.online/coverage-report?utm_source=nrl-odds-api-python&utm_medium=readme)
  measures the **racing** feed, so its count is not the NRL number — the six
  above is, measured 2026-09-15 on two fixtures. Betfair Exchange and Pinnacle
  are excluded from API responses entirely.
- **`selection_side` is a heuristic.** It resolved every string in the captured
  NRL, NRLW and Super League data and every case in `selftest.py`, but it is
  token matching against the event's own team names, not a club registry.
  Unfamiliar naming can still produce `unknown`, and it has only been exercised
  on rugby league. `fetch_nrl.py` prints a warning line counting unmatched rows
  — check it before loading a CSV into anything.
- **`track.py --demo` is half-blind to price moves.** The keyless feed reports
  only the best book per selection, and `bookmaker` is part of the series key,
  so when the best book changes a new series starts silently instead of a change
  being recorded. Only a move at the same book is detected. `--demo` is there to
  show you the shape; use a key for real change detection.
- **`track.py` has no scheduler, no daemon and no resume.** It is a loop. For
  anything serious put a single `--count 1` invocation behind cron or a systemd
  timer, which also means a crash does not end the series.
- **The history CSV grows without bound** and is never compacted. It is a log
  file. Rotate it yourself.
- **The demo path is a truncated sample** with best-price-only data and no event
  ids. It exists so you can see the shape before registering; do not build
  against it.
- **No rate-limit backoff.** The API advertises a per-minute limit per key by
  plan (it returns an `X-RateLimit-Policy` header). These scripts do not track
  it and will raise on a limit response rather than sleep and retry. That is why
  `--count > 1` insists on an `--interval`. A 429 was never actually provoked
  during this build, so the raise path is reasoned, not observed.
- **Times are UTC.** NRL kickoffs display in UTC, not AEST/AEDT. Convert before
  showing anything to a human.
- **`selftest.py` is a script, not a suite.** There is no pytest on the machine
  this was built on, so it is run by hand and returns a non-zero exit on
  failure.

## Related

PuntersEdge guides:

- [NRL odds API developer guide](https://puntersedge.online/blog/nrl-odds-api-developer-guide?utm_source=nrl-odds-api-python&utm_medium=readme)
- [NRL odds API (Australia)](https://puntersedge.online/nrl-odds-api-australia?utm_source=nrl-odds-api-python&utm_medium=readme)
- [Building a betting model data pipeline in Python](https://puntersedge.online/blog/betting-model-data-pipeline-python?utm_source=nrl-odds-api-python&utm_medium=readme)
- [Sports odds API for Australia](https://puntersedge.online/developers/sports-odds-api-australia?utm_source=nrl-odds-api-python&utm_medium=readme)
- [How to compare bookmaker odds in Australia](https://puntersedge.online/blog/how-to-compare-bookmaker-odds-australia?utm_source=nrl-odds-api-python&utm_medium=readme)
- [API reference](https://puntersedge.online/developers/api-reference?utm_source=nrl-odds-api-python&utm_medium=readme)
  · [Getting started](https://puntersedge.online/developers/getting-started?utm_source=nrl-odds-api-python&utm_medium=readme)
- Interactive API docs: [api.puntersedge.online/docs](https://api.puntersedge.online/docs)
  · [OpenAPI spec](https://api.puntersedge.online/openapi.json)

Sibling repositories:

- [puntersedge-python](https://github.com/Propertyscout001/puntersedge-python) — the official Python SDK (PyPI), if you would rather not hand-roll an HTTP client
- [puntersedge-node](https://github.com/Propertyscout001/puntersedge-node) — Node/TypeScript SDK
- [puntersedge-mcp](https://github.com/Propertyscout001/puntersedge-mcp) — MCP server, for using this data from an LLM agent
- [puntersedge-examples](https://github.com/Propertyscout001/puntersedge-examples) — standalone single-file examples across racing and sports
- [au-racing-odds-dashboard](https://github.com/Propertyscout001/au-racing-odds-dashboard) — next-to-go racing, terminal and HTML

Gambling help in Australia is national: **1800 858 858**, or
[Gambling Help Online](https://www.gamblinghelponline.org.au/).

## Licence

MIT. See [LICENSE](LICENSE).

---
18+ only. Gambling can be addictive — please gamble responsibly.
Gambling Help: 1800 858 858 · https://www.gambleaware.nsw.gov.au
This repository is a developer example for reading an odds data feed. It is not betting
advice, it places no bets and it holds no bookmaker credentials.
