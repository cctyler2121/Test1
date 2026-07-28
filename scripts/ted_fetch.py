#!/usr/bin/env python3
"""Pull Contract Award Notices from the live TED Search API v3, scoped to a
configurable set of buyer countries / CPV code prefixes / date range, and
write a normalized dataset for the dashboard.

Must be run from an environment with real internet access (TED is not
reachable from some sandboxed CI/dev environments) — a GitHub Actions runner
works. See README.md for how this fits into the scheduled pipeline.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from ecb_rates import RateTable, download_rates  # noqa: E402
from entity_resolution import resolve_companies, summarize  # noqa: E402

BASE = "https://api.ted.europa.eu/v3/notices/search"

# --- Scope: adjust these to change what the pipeline pulls -----------------
# Buyer countries (ISO 3166-1 alpha-3, TED's convention) — i.e. tenders run
# BY these countries' contracting authorities, regardless of who wins.
BUYER_COUNTRIES = ["DNK", "SWE", "NOR", "FIN", "DEU"]
# CPV division prefixes: 79=business/consulting/research services,
# 73=R&D services, 85=health & social work, 90=environmental services.
CPV_PREFIXES = ["79", "73", "85", "90"]
# eForms became mandatory for above-threshold EU procurement in late 2023;
# notices from before that don't reliably expose structured `winner-name`
# through this API regardless of query filters (confirmed empirically —
# see README's "Known limitations"), so starting earlier mostly burns the
# page budget on notices this pipeline can never attribute to a winner.
DATE_FROM = "20240101"
# -----------------------------------------------------------------------

FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-country",
    "classification-cpv",
    "winner-name",
    "winner-country",
    "winner-decision-date",
    "total-value",
    "total-value-cur",
    "publication-date",
    "links",
]

PAGE_LIMIT = 250
MAX_PAGES = 200  # safety valve: up to 50,000 notices per run
REQUEST_DELAY_SECONDS = 0.3


def build_query():
    # No total-value filter: it doesn't correlate with winner-name presence
    # (confirmed empirically — some awards carry total-value=0, some
    # notices with a positive total-value have no winner at all), so it
    # only discarded valid records without concentrating useful ones.
    # Notices with no winner are filtered out later, in flatten_notice().
    cpv_clause = " OR ".join(f"classification-cpv={p}*" for p in CPV_PREFIXES)
    country_list = ", ".join(BUYER_COUNTRIES)
    return (
        f"publication-date>={DATE_FROM} AND "
        f"({cpv_clause}) AND "
        f"buyer-country IN ({country_list})"
    )


def post(payload, timeout=30):
    req = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"TED API error {e.code}: {body[:1000]}")


NEXT_TOKEN_KEYS = ["iterationNextToken", "nextToken", "cursor", "scrollId"]


def fetch_all_notices(query):
    notices = []
    payload = {
        "query": query,
        "fields": FIELDS,
        "limit": PAGE_LIMIT,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "ITERATION",
    }
    for page_num in range(1, MAX_PAGES + 1):
        status, data = post(payload)
        page_notices = data.get("notices", [])
        notices.extend(page_notices)
        print(
            f"page {page_num}: +{len(page_notices)} notices "
            f"(total so far: {len(notices)})",
            flush=True,
        )
        if not page_notices or len(page_notices) < PAGE_LIMIT:
            break
        token_key = next((k for k in NEXT_TOKEN_KEYS if k in data), None)
        if not token_key:
            print(
                "WARNING: full page returned but no recognized pagination "
                f"token key found among {NEXT_TOKEN_KEYS}; response keys were "
                f"{list(data.keys())}. Stopping to avoid duplicate/missing data.",
                flush=True,
            )
            break
        payload[token_key] = data[token_key]
        time.sleep(REQUEST_DELAY_SECONDS)
    else:
        print(f"WARNING: hit MAX_PAGES={MAX_PAGES} safety cap; data may be incomplete.", flush=True)
    return notices


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_text(multilang_dict_or_value):
    """buyer-name/notice-title come back as {"eng": ["..."], "fra": [...]}
    (or occasionally a flat value) — take the first available string."""
    if not multilang_dict_or_value:
        return None
    if isinstance(multilang_dict_or_value, dict):
        for values in multilang_dict_or_value.values():
            if values:
                return values[0] if isinstance(values, list) else values
        return None
    if isinstance(multilang_dict_or_value, list):
        return multilang_dict_or_value[0] if multilang_dict_or_value else None
    return multilang_dict_or_value


def all_texts(multilang_dict_or_value):
    """winner-name comes back the same shape as buyer-name — a dict keyed
    by language code, e.g. {"deu": ["Company A", "Company B"]} — but unlike
    buyer-name we need every winner, not just the first. Flattens to a
    plain list of strings regardless of whether the API gave a dict, a
    flat list, or a single scalar."""
    if not multilang_dict_or_value:
        return []
    if isinstance(multilang_dict_or_value, dict):
        out = []
        for values in multilang_dict_or_value.values():
            if isinstance(values, list):
                out.extend(values)
            elif values:
                out.append(values)
        return out
    if isinstance(multilang_dict_or_value, list):
        return multilang_dict_or_value
    return [multilang_dict_or_value]


def flatten_notice(notice, rate_table):
    """One TED notice can have multiple winners (multi-lot awards). Emit one
    flat award record per distinct winner. When the API gives a single
    notice-level total-value rather than a per-winner breakdown, split it
    evenly across distinct winners — a documented approximation, not a
    per-lot join (the flat search API doesn't expose lot-to-winner
    correspondence; true precision would require fetching each notice's
    full XML)."""
    winners = all_texts(notice.get("winner-name"))
    distinct_winners = list(dict.fromkeys(w for w in winners if w))
    if not distinct_winners:
        return []

    values = as_list(notice.get("total-value"))
    currencies = as_list(notice.get("total-value-cur"))
    publication_date = notice.get("publication-date", "")[:10]

    if len(values) == len(distinct_winners) and values:
        per_winner_value = list(zip(distinct_winners, values))
    else:
        total = sum(v for v in values if isinstance(v, (int, float))) or (values[0] if values else None)
        share = (total / len(distinct_winners)) if isinstance(total, (int, float)) else None
        per_winner_value = [(w, share) for w in distinct_winners]

    currency = currencies[0] if currencies else None
    buyer_name = first_text(notice.get("buyer-name"))
    buyer_country = as_list(notice.get("buyer-country"))
    buyer_country = buyer_country[0] if buyer_country else None
    cpv_codes = sorted(set(as_list(notice.get("classification-cpv"))))
    notice_title = first_text(notice.get("notice-title"))
    html_link = None
    links = notice.get("links") or {}
    html_links = links.get("html") or {}
    html_link = html_links.get("ENG") or next(iter(html_links.values()), None)

    records = []
    for winner_name, value in per_winner_value:
        value_eur = (
            rate_table.to_eur(value, currency, publication_date)
            if value is not None and currency
            else None
        )
        records.append(
            {
                "publication_number": notice.get("publication-number"),
                "notice_title": notice_title,
                "buyer_name": buyer_name,
                "buyer_country": buyer_country,
                "cpv_codes": cpv_codes,
                "winner_name": winner_name,
                "publication_date": publication_date,
                "total_value": value,
                "total_value_cur": currency,
                "total_value_eur": value_eur,
                "notice_url": html_link,
                "multi_winner_notice": len(distinct_winners) > 1,
            }
        )
    return records


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)

    print("Downloading ECB historical exchange rates...", flush=True)
    rate_table = RateTable(download_rates())

    query = build_query()
    print(f"Query: {query}", flush=True)
    notices = fetch_all_notices(query)
    print(f"Fetched {len(notices)} raw notices", flush=True)

    records = []
    for notice in notices:
        records.extend(flatten_notice(notice, rate_table))
    print(f"Flattened to {len(records)} winner-level award records", flush=True)

    with open(os.path.join(out_dir, "contract_awards.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    alias_path = os.path.join(out_dir, "company_aliases.json")
    groups = resolve_companies(records, alias_path=alias_path)
    companies = summarize(groups)
    with open(os.path.join(out_dir, "companies.json"), "w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)

    print(f"Resolved {len(records)} records into {len(companies)} canonical companies", flush=True)

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "buyer_countries": BUYER_COUNTRIES,
        "cpv_prefixes": CPV_PREFIXES,
        "date_from": DATE_FROM,
        "notice_count": len(notices),
        "record_count": len(records),
        "company_count": len(companies),
    }
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
