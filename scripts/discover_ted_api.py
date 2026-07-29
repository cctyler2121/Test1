#!/usr/bin/env python3
"""Fourth-pass diagnostic: notice 589103-2024 (Banedanmark, Rambøll) shows
total-value=45,000,000,000 DKK (~EUR 6.03bn) for what looks like a
framework-agreement re-tender. Need to know whether that's a framework
ceiling or an actual call-off/award value, and whether a more specific
field (result-value-lot, tender-value, etc.) represents the real awarded
amount per winner. Run from an environment with real internet access.
"""
import json
import urllib.error
import urllib.request

BASE = "https://api.ted.europa.eu/v3/notices/search"

VALUE_FIELDS = [
    "publication-number",
    "notice-title",
    "winner-name",
    "total-value",
    "total-value-cur",
    "tender-value",
    "tender-value-cur",
    "tender-value-lowest",
    "tender-value-highest",
    "tender-value-cur-lowest",
    "tender-value-cur-highest",
    "result-value-lot",
    "result-value-notice",
    "result-value-cur-lot",
    "result-value-cur-notice",
    "framework-maximum-value-glo",
    "framework-maximum-value-lot",
    "framework-maximum-value-cur-glo",
    "framework-maximum-value-cur-lot",
    "framework-estimated-value",
    "framework-estimated-value-cur",
    "framework-value-notice",
    "framework-value-cur-notice",
    "result-framework-maximum-value-notice",
    "result-framework-maximum-value-cur-notice",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "estimated-value-lot",
    "estimated-value-cur-lot",
]


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
    print("=== All value-related fields for notice 589103-2024 ===", flush=True)
    status, body = post(
        {
            "query": "publication-number=589103-2024",
            "fields": VALUE_FIELDS,
            "limit": 1,
            "scope": "ALL",
            "checkQuerySyntax": False,
        }
    )
    print(status, flush=True)
    try:
        data = json.loads(body)
        notices = data.get("notices", [])
        if not notices:
            print("No notice found. Raw body:", body[:2000])
            return
        notice = notices[0]
        for field in VALUE_FIELDS:
            print(f"{field}: {notice.get(field)!r}")
    except Exception as e:
        print("parse failed:", e, body[:2000])

    print("\n=== Same fields on a handful of other 2024+ notices in scope, for comparison ===", flush=True)
    status, body = post(
        {
            "query": (
                "publication-date>=20240101 AND "
                "(classification-cpv=79* OR classification-cpv=73* OR classification-cpv=85* OR classification-cpv=90*) "
                "AND buyer-country IN (DNK, SWE, NOR, FIN, DEU)"
            ),
            "fields": VALUE_FIELDS,
            "limit": 5,
            "scope": "ALL",
            "checkQuerySyntax": False,
        }
    )
    print(status, flush=True)
    try:
        data = json.loads(body)
        for notice in data.get("notices", []):
            print(f"--- {notice.get('publication-number')} ---")
            for field in VALUE_FIELDS:
                val = notice.get(field)
                if val is not None:
                    print(f"  {field}: {val!r}")
    except Exception as e:
        print("parse failed:", e, body[:2000])


if __name__ == "__main__":
    main()
