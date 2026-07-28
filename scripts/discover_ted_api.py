#!/usr/bin/env python3
"""Third-pass diagnostic: the real production fetch (ted_fetch.py) pulled
50,000 real notices matching our scope query but extracted zero winner-name
values from any of them. This checks whether that's specific to older
(pre-eForms, likely pre-mid-2023) notices — TED's Search API abstracts over
two different underlying notice schemas, and older notices may not populate
`winner-name` the same way through this field API — or something wrong with
the `total-value>0` filter itself.
"""
import json
import urllib.error
import urllib.request

BASE = "https://api.ted.europa.eu/v3/notices/search"

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


def run(label, query, limit=3):
    print(f"\n=== {label} ===", flush=True)
    print(f"query: {query}", flush=True)
    status, body = post(
        {"query": query, "fields": FIELDS, "limit": limit, "scope": "ALL", "checkQuerySyntax": False}
    )
    print(status)
    try:
        data = json.loads(body)
        notices = data.get("notices", [])
        print(f"got {len(notices)} notices")
        for n in notices:
            keys_present = sorted(n.keys())
            print(f"  publication-number={n.get('publication-number')} keys_present={keys_present}")
            print(f"    winner-name={n.get('winner-name')!r}")
            print(f"    total-value={n.get('total-value')!r} total-value-cur={n.get('total-value-cur')!r}")
    except Exception as e:
        print("parse failed:", e, body[:2000])


PROD_SCOPE = (
    "(classification-cpv=79* OR classification-cpv=73* OR classification-cpv=85* OR classification-cpv=90*) "
    "AND buyer-country IN (DNK, SWE, NOR, FIN, DEU)"
)

run(
    "A: exact production query, oldest end (2018)",
    f"publication-date>=20180101 AND {PROD_SCOPE} AND total-value>0",
)
run(
    "B: same scope, no total-value filter at all (2018)",
    f"publication-date>=20180101 AND {PROD_SCOPE}",
)
run(
    "C: same scope, recent/eForms-era date (2024-06 onward)",
    f"publication-date>=20240601 AND {PROD_SCOPE} AND total-value>0",
)
run(
    "D: recent date, no total-value filter",
    f"publication-date>=20240601 AND {PROD_SCOPE}",
)
run(
    "E: very recent (last 60 days), no filter beyond scope",
    f"publication-date>=20260501 AND {PROD_SCOPE}",
)
