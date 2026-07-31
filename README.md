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
                               its notice date, tags each record with a
                               market category (see below), writes:
                                 data/contract_awards.json (flat records — not committed, see below)
                                 data/metadata.json (run info)
scripts/entity_resolution.py → groups records by normalized winner name
                               (strips legal-form suffixes: GmbH, S.A.,
                               Ltd, Sp. z o.o., B.V., Oy, AB, ...), with a
                               manual override file for cases automatic
                               normalization gets wrong. Writes:
                                 data/companies.json.gz (rolled-up per-company view, gzipped)
scripts/market_categories.py → maps a notice's CPV code(s) to one market
                               category (Wind Energy, Roads & Highways,
                               Defence & Security Equipment, etc.) — see
                               "Market categories" below
scripts/market_trends.py    → buckets records by calendar quarter (EU-wide
                               and per-country) into category/buyer/
                               contractor rollups plus quarter-over-quarter
                               trend flags. Writes:
                                 data/market_trends.json
scripts/ecb_rates.py         → downloads ECB historical daily FX rates for
                               currency conversion
dashboard/index.html         → static page reading data/companies.json.gz
                               (decompressed client-side via the browser's
                               native DecompressionStream), data/metadata.json,
                               and data/market_trends.json: a "this quarter"
                               market-trends panel, company search with
                               rolled-up totals, and expandable legal-entity
                               variants and underlying contracts
```

`.github/workflows/ted-fetch.yml` runs `ted_fetch.py` on a schedule and
commits the refreshed `data/companies.json.gz` and `data/metadata.json` —
that's what keeps the dashboard "live" without any session needing direct
network access to TED. `data/contract_awards.json` (the raw flat dump,
unused by the dashboard) is uploaded as a 30-day GitHub Actions build
artifact instead of committed, to keep the git repo from growing by tens
of megabytes every single day forever.

`companies.json` is committed gzipped, not plain: at full-EU scope
(~206k award records) the plain file measured 99.6MB, essentially at
GitHub's 100MB per-file push limit. Gzip got it down to a comfortable
fraction of that (structured JSON with this much repetition compresses
~6-8x). The dashboard fetches the `.gz` file and decompresses it in the
browser — no server-side involvement, no build step, no added JS
dependency (`DecompressionStream` is native in Chrome/Edge 80+, Firefox
113+, Safari 16.4+).

**The daily schedule only takes effect once this workflow is on `main`** —
GitHub only fires `schedule:` triggers from the repository's default
branch. Until this is merged, use the workflow's manual "Run workflow"
button to refresh data on a feature branch.

## Adjusting scope

Edit the constants at the top of `scripts/ted_fetch.py`:

- `BUYER_COUNTRIES` — ISO 3166-1 alpha-3 codes for the contracting
  authorities' countries (i.e. where the tender was run, not where the
  winner is based). Currently all 27 EU member states plus Norway (EEA,
  publishes above-threshold notices to TED same as EU members).
- `CPV_PREFIXES` — CPV prefixes to include. The original four are whole
  divisions: `79` (business/consulting/research services), `73` (R&D
  services), `85` (health & social work), `90` (environmental services).
  The market-trends additions are deliberately narrower than their parent
  divisions — divisions `45` (Construction work, 424K+ notices in scope)
  and `71` (Architectural/engineering, 270K+ notices) are dominated by
  generic building/renovation work unrelated to any tracked category, so
  only specific group-level codes are included: `09` (energy), `31121300`
  (wind-energy generators specifically, not all electrical machinery),
  `35` (security/defence equipment), `45233` (roads), `45234` (rail),
  `45241` (harbours), `45251` (power plant construction), `72` (IT/digital
  services). Every prefix here was verified against live TED data first
  (see `scripts/discover_cpv_taxonomy.py`) rather than assumed from the CPV
  spec — see "Market categories" below for what's still uncertain.
- `DATE_FROM` — coverage start date (`YYYYMMDD`), currently `20240101` (see
  "Known limitations" for why it isn't set earlier).

Widening scope significantly (e.g. all CPV codes instead of the current
four divisions) will increase the number of notices well into the
millions. `MAX_PAGES` in `ted_fetch.py` is now a circuit breaker against a
runaway/looping bug (8,000 pages × 250 notices = 2,000,000), not a real
cap on the current scope — raising it further only matters if you widen
scope enough to actually hit it. The real limit to watch is
**`companies.json.gz` staying under GitHub's 100MB per-file push limit**:
`ted_fetch.py` refuses to write one over 90MB (raises instead of producing
a file the workflow's `git push` would just reject). If you hit that
ceiling even gzipped, narrow scope (fewer CPV codes, shorter date range)
or shard the data across multiple committed files — raising the limit
further isn't an option, that's GitHub's own ceiling.

## Market categories

Each award record is tagged with one market category (`scripts/market_categories.py`) derived from its CPV code(s), used by the dashboard's "this quarter" trends panel. A notice can carry multiple CPV codes describing different facets of the same contract; the category mapping is priority-ordered (most specific first) so a notice that's physically a wind-farm contract but also touches consulting services is tagged "Wind Energy," not "Consulting."

Two gaps worth knowing before reading too much into the categorized data:

- **Nuclear isn't split out from power-plant construction generally.** CPV code `45251*` covers power-plant construction broadly (thermal, hydro, gas, district-heating, and presumably nuclear), and probing the live API didn't turn up a distinct, confirmed nuclear-specific subcode (a first guess, `45262*`, turned out to be generic "specialist construction" — concrete repair, supporting walls — not nuclear at all). Nuclear contracts currently fall under "Power Plants (General)" rather than their own category.
- **"Defence & Security Equipment" likely won't reflect military procurement volume.** Sampling CPV division `35` against live data returned firefighting vehicles, CCTV/surveillance systems, and general security equipment — not weapons or classified military contracts. This tracks with EU rules (Treaty Article 346 lets member states exempt sensitive military procurement from public tender publication), so this category is expected to skew toward public-safety equipment rather than defence spend in the colloquial sense.

Refining either of these doesn't require a re-fetch: categorization runs as a post-processing step over each record's already-stored `cpv_codes`, so a taxonomy fix in `scripts/market_categories.py` takes effect on the next scheduled run.

## Known limitations

- **Coverage effectively starts in the eForms era (~2024), not 2018.**
  Confirmed empirically against the live API: pre-eForms notices (eForms
  became mandatory for above-threshold EU procurement in late 2023)
  consistently come back with no `winner-name` at all through this Search
  API, regardless of query filters — sampled 2018 notices with a real
  `total-value` still had `winner-name=None`, while 2024+ samples reliably
  carry populated, multi-winner `winner-name` data. `DATE_FROM` defaults to
  `20240101` so the page budget isn't spent on notices this pipeline can
  never attribute to a winner; the source TED dashboard's 2018 start date
  isn't achievable through this field, at least not without a different
  data path (e.g. parsing full per-notice XML instead of the flat search
  fields).
- **No reliable query-side filter for "this notice has a winner".** A
  `total-value>0` filter looks like it should proxy for "this is an award
  notice," but doesn't: some real awards carry `total-value=0` (e.g.
  framework agreements), and some notices with a positive `total-value`
  have no winner at all (likely an estimated value on a still-open
  tender). The API's expert-query syntax also doesn't support `IS NOT
  NULL`/`EXISTS()`-style existence checks (confirmed — both are syntax
  errors). So this pipeline fetches broadly within the CPV/country/date
  scope and filters for a populated `winner-name` client-side, after the
  fetch, discarding notices with no winner.
- **A notice's `total-value` can be a framework ceiling, not an actual
  award/spend amount, with no way to tell the two apart via this API.**
  Confirmed on a real notice (Banedanmark/Rambøll, publication 589103-2024,
  a "Rammeaftale" framework re-tender): `total-value` was 45B DKK
  (~EUR 6.03bn), and TED's own `result-value-notice` field — which should
  represent the actual outcome value — agreed with it exactly, while every
  dedicated framework-ceiling field (`framework-maximum-value-*`,
  `framework-estimated-value`, `framework-value-notice`) was empty for that
  notice. So TED's own system doesn't consistently separate "ceiling" from
  "amount actually spent" for frameworks, at least not in a way this API
  exposes — an unusually large number for one notice is worth checking the
  linked notice for before relying on it, particularly for framework
  agreements. (An earlier version of the dashboard auto-flagged large
  values with a badge; removed because at the top of any "biggest
  contracts" view, nearly everything is large by construction, so the
  badge fired almost everywhere and stopped being a useful signal.)
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
