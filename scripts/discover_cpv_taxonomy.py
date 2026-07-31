#!/usr/bin/env python3
"""Fifth-pass diagnostic: ground-truth CPV code candidates for the market-
trends taxonomy (energy incl. wind/nuclear, transport infra incl.
roads/rail/ports, defence & security, general construction, IT/digital
services) against the live TED API, instead of trusting an 8-digit CPV code
from memory. For each candidate prefix, fetches a match count and a small
sample of real notices (title, CPV codes, buyer/winner names) so the
taxonomy mapping in scripts/market_categories.py can be built from actual
observed data. Run from an environment with real internet access (GitHub
Actions, not this sandbox — see README).
"""
import json
import urllib.error
import urllib.request

BASE = "https://api.ted.europa.eu/v3/notices/search"

SAMPLE_FIELDS = [
    "publication-number",
    "notice-title",
    "classification-cpv",
    "buyer-name",
    "buyer-country",
    "winner-name",
    "total-value",
    "total-value-cur",
    "publication-date",
]

# Candidate CPV prefixes to probe. Division-level (2-digit) entries confirm
# whether a whole division is worth including in the fetch scope; the more
# specific group/class-level entries (4-8 digit) are candidates for splitting
# that division into finer market categories (e.g. "wind" vs "nuclear" both
# live somewhere under division 45).
CANDIDATES = {
    "09 - Energy (division)": "09",
    "31 - Electrical machinery/equipment (division)": "31",
    "34 - Transport equipment (division)": "34",
    "35 - Security/defence equipment (division)": "35",
    "44 - Construction structures/materials (division)": "44",
    "45 - Construction work (division)": "45",
    "71 - Architectural/engineering services (division)": "71",
    "72 - IT services (division)": "72",
    "45251 - candidate: power plant construction": "45251",
    "45262 - candidate: specialist construction incl. nuclear": "45262",
    "45233 - candidate: road/highway construction": "45233",
    "45234 - candidate: railway construction": "45234",
    "45241 - candidate: harbour construction": "45241",
    "45213 - candidate: multi-storey/industrial structures": "45213",
    "09330 - candidate: solar energy": "09330",
    "31121 - candidate: generators/wind turbines": "31121",
}

DATE_FROM = "20240101"


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


def probe(label, cpv_prefix):
    print(f"\n=== {label} (classification-cpv={cpv_prefix}*) ===", flush=True)
    query = f"publication-date>={DATE_FROM} AND classification-cpv={cpv_prefix}*"
    status, body = post(
        {
            "query": query,
            "fields": SAMPLE_FIELDS,
            "limit": 5,
            "scope": "ALL",
            "checkQuerySyntax": False,
        }
    )
    print("status:", status, flush=True)
    try:
        data = json.loads(body)
    except Exception as e:
        print("parse failed:", e, body[:1000] if isinstance(body, str) else body)
        return
    total = data.get("totalNoticeCount") or data.get("totalCount") or data.get("total")
    print("reported total count field(s):", {k: v for k, v in data.items() if "total" in k.lower() or "count" in k.lower()})
    notices = data.get("notices", [])
    print(f"sample size: {len(notices)}")
    for notice in notices:
        print("  ---")
        for field in SAMPLE_FIELDS:
            val = notice.get(field)
            if val is not None:
                print(f"    {field}: {val!r}")


def main():
    for label, prefix in CANDIDATES.items():
        probe(label, prefix)


if __name__ == "__main__":
    main()
