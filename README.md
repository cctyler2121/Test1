# Test1

EU contract-award dashboard: pulls Contract Award Notices from the live
[TED Search API v3](https://docs.ted.europa.eu/api/latest/index.html),
groups winners across their different legal-entity name variants into a
single canonical company, and shows the rolled-up totals in a searchable
static dashboard.

## Why it's built this way

The dashboard at ted.europa.eu is a client-rendered widget with no public
aggregate data feed, so this project goes straight to TED's own public
Search API for the underlying Contract Award Notices instead of scraping
the widget.

Some execution environments (including the one this was originally built
in) block outbound access to `*.europa.eu` at the network-policy level —
not a TED-side block, a local egress restriction. **GitHub Actions runners
are not behind that restriction**, so the actual data pull runs as a
scheduled GitHub Action rather than from a dev session, and its logs are
the debugging channel when something about the API needs to change.

## Pipeline

```
scripts/ted_fetch.py        → queries the TED Search API, paginates through
                               all matching notices, converts each award's
                               value to EUR at the ECB reference rate for
                               its notice date, writes:
                                 data/contract_awards.json (flat records)
                                 data/metadata.json (run info)
scripts/entity_resolution.py → groups records by normalized winner name
                               (strips legal-form suffixes: GmbH, S.A.,
                               Ltd, Sp. z o.o., B.V., Oy, AB, ...), with a
                               manual override file for cases automatic
                               normalization gets wrong. Writes:
                                 data/companies.json (rolled-up per-company view)
scripts/ecb_rates.py         → downloads ECB historical daily FX rates for
                               currency conversion
dashboard/index.html         → static page reading data/*.json: search by
                               company name, see rolled-up totals, expand
                               to see legal-entity variants and underlying
                               contracts
```

`.github/workflows/ted-fetch.yml` runs `ted_fetch.py` on a schedule and
commits the refreshed `data/*.json` files — that's what keeps the
dashboard "live" without any session needing direct network access to TED.

## Adjusting scope

Edit the constants at the top of `scripts/ted_fetch.py`:

- `BUYER_COUNTRIES` — ISO 3166-1 alpha-3 codes for the contracting
  authorities' countries (i.e. where the tender was run, not where the
  winner is based). Currently `DNK, SWE, NOR, FIN, DEU`.
- `CPV_PREFIXES` — CPV division prefixes to include. Currently `79`
  (business/consulting/research services), `73` (R&D services), `85`
  (health & social work), `90` (environmental services).
- `DATE_FROM` — coverage start date (`YYYYMMDD`), currently `20180101`.

Widening scope significantly (e.g. all EU countries, all CPV codes) will
increase the number of notices well into the millions — `MAX_PAGES` in
`ted_fetch.py` is a safety valve (currently 200 pages × 250 notices =
50,000) to keep a single Action run bounded; raise it deliberately, and
expect a much longer run and a much bigger committed dataset.

## Known limitations

- **Multi-winner notices**: the TED Search API's flat `fields` response
  doesn't expose which winner corresponds to which lot when a notice has
  several. When a notice has multiple distinct winners, this pipeline
  splits the notice's total award value evenly across them (flagged as
  `multi_winner_notice: true` on the record, and with a footnote in the
  dashboard). Getting exact per-lot amounts would require fetching and
  parsing each notice's full XML instead of the flat search fields —
  a much heavier pull.
- **Entity resolution is automatic + overridable, not perfect**: real
  company names are messy (typos, mid-history renames, holding-company
  restructuring). Automatic normalization handles legal-form suffixes and
  spelling/punctuation noise; anything it gets wrong (over-merging two
  different companies, or failing to merge two spellings of the same one)
  can be fixed in `data/company_aliases.json`:
  ```json
  { "Canonical Company Name": ["Exact winner-name variant 1", "Exact winner-name variant 2"] }
  ```
  Re-run `scripts/ted_fetch.py` (or wait for the next scheduled run) after
  editing it.
- **Scheduled runs only fire on the default branch** — a GitHub
  restriction, not something this repo controls. While developing on a
  feature branch, use the workflow's manual "Run workflow" button instead.

## Running locally

```
python3 scripts/ted_fetch.py     # needs real internet access to ted.europa.eu
python3 -m http.server           # serve the repo root
# open http://localhost:8000/dashboard/index.html
```

The dashboard fetches `../data/*.json` at runtime, so it needs to be served
over HTTP — opening `index.html` directly via `file://` will fail on the
fetch calls in most browsers.
