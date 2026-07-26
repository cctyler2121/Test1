#!/usr/bin/env python3
"""One-off probe of the live TED Search API v3 to confirm exact query/field
names before the real fetch script is written. Run from an environment with
real internet access (e.g. a GitHub Actions runner) — output goes to the job
log, not to any repo file.
"""
import json
import urllib.error
import urllib.request

BASE = "https://api.ted.europa.eu/v3/notices/search"


def post(payload):
    req = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # network errors etc.
        return None, repr(e)


def main():
    print("=== Step 1: baseline query ===", flush=True)
    status, body = post(
        {
            "query": "publication-date>=20240101",
            "fields": ["publication-number"],
            "limit": 1,
            "scope": "ALL",
            "checkQuerySyntax": False,
            "paginationMode": "ITERATION",
        }
    )
    print(status)
    print(body[:2000])

    print("\n=== Step 2: probe expert-query field names ===", flush=True)
    query_fragments = [
        "classification-cpv=79*",
        "classification-cpv IN (79000000, 73000000, 85000000, 90000000)",
        "buyer-country=DNK",
        "place-of-performance=DNK",
        "notice-type=can",
        "winner-country=DEU",
    ]
    for qf in query_fragments:
        status, body = post(
            {
                "query": f"publication-date>=20240101 AND {qf}",
                "fields": ["publication-number"],
                "limit": 1,
                "scope": "ALL",
                "checkQuerySyntax": True,
            }
        )
        ok = status == 200
        print(f"{qf!r} -> {status} {'OK' if ok else body[:400]}")

    print("\n=== Step 3: probe result field names ===", flush=True)
    candidate_fields = [
        "winner-name",
        "winner-country",
        "winner-decision-date",
        "organisation-name-winner",
        "total-value",
        "total-value-cur",
        "contract-award-value",
        "contract-award-value-cur",
        "tender-value-lowest",
        "tender-value-highest",
        "buyer-name",
        "buyer-country",
        "classification-cpv",
        "publication-date",
        "notice-title",
        "links",
    ]
    for f in candidate_fields:
        status, body = post(
            {
                "query": "publication-date>=20240101",
                "fields": ["publication-number", f],
                "limit": 1,
                "scope": "ALL",
                "checkQuerySyntax": False,
            }
        )
        ok = status == 200
        print(f"{f} -> {status} {'OK: ' + body[:300] if ok else body[:300]}")


if __name__ == "__main__":
    main()
