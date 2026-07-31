"""Market-category taxonomy for the market-intelligence dashboard feature.

Maps a notice's CPV codes to one human-readable market category. Every
prefix here was verified against live TED data before being added (see
scripts/discover_cpv_taxonomy.py and its GitHub Actions run) rather than
assumed from the CPV spec alone — division 45 ("Construction work") in
particular contains far more than infrastructure (swimming pools,
scaffolding, generic renovations), so categories are scoped to the
specific group/class-level codes confirmed to actually mean what their
name suggests, not whole divisions.

A single notice can carry many CPV codes describing different facets of
the same contract. CATEGORY_RULES is ordered most-specific-first; the
first rule whose prefix matches any of the notice's CPV codes wins. This
intentionally favors "this is physically a wind farm contract" over "this
also happens to touch consulting services" when a notice carries both.

Known gap (see README): CPV alone doesn't cleanly distinguish nuclear from
other power-plant construction — 45251* covers power plants generally
(thermal, hydro, gas, district-heating, and presumably nuclear) without a
confirmed distinct subcode. Until that's pinned down empirically, nuclear
contracts fall under "Power Plants (General)" rather than their own
category.
"""

CATEGORY_RULES = [
    ("Wind Energy", "31121300"),
    ("Solar Energy", "0933"),
    ("Power Plants (General)", "45251"),
    ("Energy (Other)", "09"),
    ("Roads & Highways", "45233"),
    ("Rail", "45234"),
    ("Ports & Maritime", "45241"),
    ("Defence & Security Equipment", "35"),
    ("Digital & IT Services", "72"),
    ("Consulting & Business Services", "79"),
    ("R&D Services", "73"),
    ("Health & Social Services", "85"),
    ("Environmental Services", "90"),
]

OTHER_CATEGORY = "Other"


def categorize(cpv_codes):
    """cpv_codes: list of CPV code strings from a notice. Returns the single
    best-matching category name, or OTHER_CATEGORY if none of the known
    prefixes match (shouldn't normally happen given the fetch query already
    filters to these prefixes, but a notice's CPV list can include codes
    outside the queried prefixes too).
    """
    if not cpv_codes:
        return OTHER_CATEGORY
    for category, prefix in CATEGORY_RULES:
        for code in cpv_codes:
            if code and code.startswith(prefix):
                return category
    return OTHER_CATEGORY
