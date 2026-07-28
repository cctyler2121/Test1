#!/usr/bin/env python3
"""Second-pass probe of the live TED Search API v3: get the full valid-field
catalog, a complete sample award record's JSON shape, and confirm how to
filter to notices that actually have a winner. Run from an environment with
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
    except Exception as e:
        return None, repr(e)


def main():
    print("=== Step 1: full valid-field catalog (via deliberate bad field) ===", flush=True)
    status, body = post(
        {
            "query": "publication-date>=20240101",
            "fields": ["publication-number", "___not_a_real_field___"],
            "limit": 1,
            "scope": "ALL",
            "checkQuerySyntax": False,
        }
    )
    print(status)
    try:
        data = json.loads(body)
        supported = data.get("error", {}).get("supportedFieldNames") or data.get("supportedFieldNames")
        if supported is None:
            msg = data.get("message", "")
            marker = "supported values are: "
            idx = msg.find(marker)
            supported = msg[idx + len(marker):] if idx != -1 else None
        if isinstance(supported, str):
            supported = [s.strip() for s in supported.split(",")]
        if supported:
            winnerish = sorted(f for f in supported if "winner" in f.lower())
            valueish = sorted(f for f in supported if "value" in f.lower())
            print(f"TOTAL FIELDS: {len(supported)}")
            print("WINNER-RELATED FIELDS:", winnerish)
            print("VALUE-RELATED FIELDS:", valueish)
        else:
            print("Could not extract field list, raw body:")
            print(body)
    except Exception as e:
        print("Parse failed:", e)
        print(body[:3000])

    print("\n=== Step 2: full sample award record ===", flush=True)
    fields = [
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
    ]
    for q in [
        "classification-cpv=79* AND publication-date>=20240101 AND winner-country=DNK",
        "classification-cpv=79* AND publication-date>=20240101 AND buyer-country=DEU",
        "publication-date>=20240101",
    ]:
        status, body = post(
            {"query": q, "fields": fields, "limit": 2, "scope": "ALL", "checkQuerySyntax": False}
        )
        print(f"query={q!r} -> {status}")
        print(body[:4000])
        print("---")

    print("\n=== Step 3: filtering to notices that actually have a winner ===", flush=True)
    for qf in [
        "winner-name IS NOT NULL",
        "winner-name <> null",
        "EXISTS(winner-name)",
        "total-value>0",
    ]:
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

    print("\n=== Step 4: pagination token check ===", flush=True)
    status, body = post(
        {
            "query": "classification-cpv=79* AND publication-date>=20240101",
            "fields": ["publication-number"],
            "limit": 2,
            "scope": "ALL",
            "checkQuerySyntax": False,
            "paginationMode": "ITERATION",
        }
    )
    print(status)
    print(body[:1500])

    print("\n=== Step 5: rough volume estimate for a candidate scoped query ===", flush=True)
    scoped_query = (
        "publication-date>=20180101 AND "
        "classification-cpv IN (79*, 73*, 85*, 90*) AND "
        "buyer-country IN (DNK, SWE, NOR, FIN, DEU)"
    )
    status, body = post(
        {"query": scoped_query, "fields": ["publication-number"], "limit": 1, "scope": "ALL", "checkQuerySyntax": False}
    )
    print(status)
    print(body[:1500])


if __name__ == "__main__":
    main()
