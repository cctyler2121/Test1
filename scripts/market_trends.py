#!/usr/bin/env python3
"""Build the market-intelligence rollups the dashboard's "this quarter"
panel (and, later, the per-country drill-down) read: for each calendar
quarter, EU-wide and per-country breakdowns of award value/count by market
category (scripts/market_categories.py), plus top buyers and top
contractors and a quarter-over-quarter trend flag per category.

Contractor names are canonicalized through the same entity resolution used
for the main company rollup (scripts/entity_resolution.py), so "top
contractors" in a given quarter reflects the same real-world companies as
the rest of the dashboard rather than raw legal-entity-variant strings.
Buyer names are not resolved — contracting-authority names don't carry the
same legal-entity-variant noise winner names do, and no buyer-side
resolution exists elsewhere in this pipeline.

Standalone usage (re-run trends without re-fetching from TED):
    python3 scripts/market_trends.py
reads data/contract_awards.json and (re)writes data/market_trends.json.
Normally called from ted_fetch.py with records already in memory.
"""
import calendar
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from entity_resolution import resolve_companies  # noqa: E402

TOP_N = 10
TREND_THRESHOLD_PCT = 15.0  # below this magnitude of change, call it "flat"


def quarter_of(publication_date):
    """'2024-03-17' -> (2024, 1). Returns None for missing/malformed dates."""
    if not publication_date or len(publication_date) < 7:
        return None
    try:
        year = int(publication_date[:4])
        month = int(publication_date[5:7])
    except ValueError:
        return None
    return (year, (month - 1) // 3 + 1)


def quarter_label(yq):
    year, q = yq
    return f"{year}-Q{q}"


def quarter_end_date(yq):
    year, q = yq
    month = q * 3
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def prior_quarter(yq):
    year, q = yq
    if q == 1:
        return (year - 1, 4)
    return (year, q - 1)


def _empty_bucket():
    return {"count": 0, "priced_count": 0, "total_value_eur": 0.0}


def _add_to_bucket(bucket, value_eur):
    bucket["count"] += 1
    if value_eur is not None:
        bucket["priced_count"] += 1
        bucket["total_value_eur"] += value_eur


def _top_n(name_buckets, n=TOP_N):
    ranked = sorted(
        name_buckets.items(),
        key=lambda kv: kv[1]["total_value_eur"],
        reverse=True,
    )
    return [
        {
            "name": name,
            "count": b["count"],
            "priced_count": b["priced_count"],
            "total_value_eur": round(b["total_value_eur"], 2),
        }
        for name, b in ranked[:n]
    ]


def _canonical_winner_map(records, alias_path):
    """raw winner_name -> canonical display_name, built once from the same
    resolution the main company rollup uses, so quarter/category "top
    contractors" names match the rest of the dashboard.
    """
    groups = resolve_companies(records, alias_path=alias_path)
    mapping = {}
    for group in groups.values():
        for variant in group["variants"]:
            mapping[variant] = group["display_name"]
    return mapping


def _build_scope(records, winner_map):
    """Aggregate one scope's (EU-wide, or a single country's) records into
    per-quarter breakdowns: by-category totals, top buyers, top
    contractors.
    """
    by_quarter = {}
    for rec in records:
        yq = quarter_of(rec.get("publication_date"))
        if yq is None:
            continue
        label = quarter_label(yq)
        bucket = by_quarter.setdefault(
            label, {"by_category": {}, "buyers": {}, "contractors": {}}
        )
        value_eur = rec.get("total_value_eur")

        category = rec.get("market_category") or "Other"
        cat_bucket = bucket["by_category"].setdefault(category, _empty_bucket())
        _add_to_bucket(cat_bucket, value_eur)

        buyer_name = rec.get("buyer_name")
        if buyer_name:
            buyer_bucket = bucket["buyers"].setdefault(buyer_name, _empty_bucket())
            _add_to_bucket(buyer_bucket, value_eur)

        winner_name = rec.get("winner_name")
        if winner_name:
            canonical = winner_map.get(winner_name, winner_name)
            contractor_bucket = bucket["contractors"].setdefault(canonical, _empty_bucket())
            _add_to_bucket(contractor_bucket, value_eur)

    result = {}
    for label, bucket in by_quarter.items():
        result[label] = {
            "by_category": {
                cat: {
                    "count": b["count"],
                    "priced_count": b["priced_count"],
                    "total_value_eur": round(b["total_value_eur"], 2),
                }
                for cat, b in bucket["by_category"].items()
            },
            "top_buyers": _top_n(bucket["buyers"]),
            "top_contractors": _top_n(bucket["contractors"]),
        }
    return result


def _category_trends(by_quarter, latest_label, prior_label):
    latest = by_quarter.get(latest_label, {}).get("by_category", {})
    prior = by_quarter.get(prior_label, {}).get("by_category", {})
    categories = set(latest) | set(prior)
    trends = []
    for category in categories:
        latest_value = latest.get(category, {}).get("total_value_eur", 0.0)
        prior_value = prior.get(category, {}).get("total_value_eur", 0.0)
        if prior_value > 0:
            pct_change = (latest_value - prior_value) / prior_value * 100
        elif latest_value > 0:
            pct_change = 100.0
        else:
            pct_change = 0.0
        if pct_change > TREND_THRESHOLD_PCT:
            direction = "up"
        elif pct_change < -TREND_THRESHOLD_PCT:
            direction = "down"
        else:
            direction = "flat"
        trends.append(
            {
                "category": category,
                "latest_value_eur": round(latest_value, 2),
                "prior_value_eur": round(prior_value, 2),
                "pct_change": round(pct_change, 1),
                "direction": direction,
            }
        )
    trends.sort(key=lambda t: t["latest_value_eur"], reverse=True)
    return trends


def build_market_trends(records, alias_path=None, today=None):
    today = today or date.today()
    winner_map = _canonical_winner_map(records, alias_path)

    eu_wide = _build_scope(records, winner_map)

    by_country_records = {}
    for rec in records:
        country = rec.get("buyer_country")
        if not country:
            continue
        by_country_records.setdefault(country, []).append(rec)
    by_country = {
        country: _build_scope(country_records, winner_map)
        for country, country_records in by_country_records.items()
    }

    all_quarters = sorted(
        {quarter_of(rec.get("publication_date")) for rec in records if quarter_of(rec.get("publication_date"))}
    )
    complete_quarters = [yq for yq in all_quarters if quarter_end_date(yq) < today]
    latest_complete = complete_quarters[-1] if complete_quarters else (all_quarters[-1] if all_quarters else None)
    prior = prior_quarter(latest_complete) if latest_complete else None

    latest_label = quarter_label(latest_complete) if latest_complete else None
    prior_label = quarter_label(prior) if prior else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_complete_quarter": latest_label,
        "prior_quarter": prior_label,
        "quarters": [quarter_label(yq) for yq in all_quarters],
        "eu_wide": eu_wide,
        "eu_wide_category_trends": (
            _category_trends(eu_wide, latest_label, prior_label) if latest_label and prior_label else []
        ),
        "by_country": by_country,
    }


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    awards_path = os.path.join(out_dir, "contract_awards.json")
    with open(awards_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    alias_path = os.path.join(out_dir, "company_aliases.json")
    trends = build_market_trends(records, alias_path=alias_path)
    trends_path = os.path.join(out_dir, "market_trends.json")
    with open(trends_path, "w", encoding="utf-8") as f:
        json.dump(trends, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(trends_path) / 1024
    print(f"Wrote {trends_path} ({size_kb:.1f} KB): "
          f"{len(trends['quarters'])} quarters, {len(trends['by_country'])} countries, "
          f"latest complete quarter {trends['latest_complete_quarter']}", flush=True)


if __name__ == "__main__":
    main()
