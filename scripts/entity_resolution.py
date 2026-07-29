"""Cluster winner-name variants (different legal entities / spellings of the
same real company) into a single canonical company, so a dashboard can show
one rolled-up row instead of 20-30 near-duplicate legal-entity names.

Approach: normalize each name (case fold, strip diacritics/punctuation, drop
common multi-language legal-form suffixes), then group by the normalized
core. An optional manual alias file lets you force-merge or force-split
groups the automatic normalization gets wrong — real-world company names are
messy enough that some manual correction is always needed.
"""
import json
import re
import unicodedata

# Legal-form suffixes/prefixes seen across EU languages. Matched as whole
# tokens after normalization, so "AB" only strips as a trailing token, not
# inside a word like "Abcompany".
LEGAL_FORM_TOKENS = {
    "ltd", "limited", "plc", "llc", "llp", "inc", "incorporated", "corp",
    "corporation", "co", "company",
    "gmbh", "ggmbh", "ag", "se", "kg", "kgaa", "ohg", "eg", "eu",
    "sa", "sas", "sarl", "sasu", "eurl",
    "spa", "srl", "srls", "sapa",
    "nv", "bv", "bvba", "cvba", "vzw",
    "oy", "oyj", "ab", "aps", "as", "asa", "ab publ",
    "kft", "zrt", "nyrt", "bt",
    "sro", "as", "kspol", "vos",
    "sia", "uab", "ab", "oü", "as",
    "doo", "dd", "javno", "shpk", "shp", "sh",
    "eood", "ood", "ad", "et",
    "srl", "sp zoo", "spzoo", "spółka", "spolka",
    "sp k", "spk",
    "ou", "oü",
    "the", "and", "und", "et", "y", "og",
}

# Multi-word legal forms that split into individual tokens after
# punctuation stripping (e.g. "Sp. z o.o." -> "sp", "z", "o", "o"), none of
# which are safe to strip as single generic tokens ("z"/"o" are ordinary
# words in several languages). Removed as contiguous sequences instead.
LEGAL_FORM_PHRASES = [
    ["sp", "z", "o", "o"],       # Polish: spółka z ograniczoną odpowiedzialnością
    ["s", "r", "o"],             # Czech/Slovak: společnost s ručením omezeným
    ["a", "s"],                  # Danish/Norwegian: aktieselskab (A/S)
    ["d", "o", "o"],             # Slovenian/Croatian/Serbian: družba z omejeno odgovornostjo
]


def _strip_phrases(tokens):
    for phrase in LEGAL_FORM_PHRASES:
        n = len(phrase)
        i = 0
        result = []
        while i < len(tokens):
            if tokens[i:i + n] == phrase:
                i += n
            else:
                result.append(tokens[i])
                i += 1
        tokens = result
    return tokens

_DIACRITIC_RE = re.compile(r"[̀-ͯ]")
_WS_RE = re.compile(r"\s+")

# Minimum length of a normalized name before it's trusted as a grouping key.
# Below this, normalization has stripped the name down to nothing
# company-specific (often a raw winner-name that is itself just a bare
# legal-form string like "SA" or "SARL" with no name at all — a TED source-
# data quality issue, not a real company). Bucketing every such record
# together under one shared empty/near-empty key falsely merges unrelated
# companies, so resolve_companies() falls back to a per-raw-name key instead
# of the normalized one when this threshold isn't met.
MIN_NORMALIZED_LENGTH = 2


def _strip_non_alnum(text):
    """Replace everything that isn't a Unicode letter/digit/space with a
    space. Unlike an ASCII-only [^a-z0-9\\s] regex, this preserves non-Latin
    scripts (Greek, Cyrillic, etc.) instead of erasing them to nothing —
    erasing them was collapsing many genuinely distinct companies down to
    the same empty string.
    """
    return "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)

# Letters that don't have a canonical Unicode decomposition (NFKD leaves
# them untouched), so they need an explicit fold — common across Nordic,
# Polish, German, and Balkan company names.
_EXTRA_CHAR_MAP = str.maketrans({
    "ø": "o", "Ø": "o",
    "æ": "ae", "Æ": "ae",
    "đ": "d", "Đ": "d",
    "ł": "l", "Ł": "l",
    "ß": "ss",
    "þ": "th", "Þ": "th",
    "ð": "d", "Ð": "d",
})


def normalize(raw_name):
    """Return a normalized core string for grouping near-duplicate names."""
    if not raw_name:
        return ""
    text = raw_name.translate(_EXTRA_CHAR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = _DIACRITIC_RE.sub("", text)
    text = text.lower()
    text = _strip_non_alnum(text)
    tokens = [t for t in text.split() if t]
    tokens = [t for t in tokens if t not in LEGAL_FORM_TOKENS]
    tokens = _strip_phrases(tokens)
    text = " ".join(tokens)
    text = _WS_RE.sub(" ", text).strip()
    return text


def load_aliases(path):
    """Manual override file: {"canonical name": ["variant a", "variant b"]}.
    Any raw winner-name in a variant list is forced into that canonical
    group regardless of what automatic normalization would produce.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    variant_to_canonical = {}
    for canonical, variants in raw.items():
        for v in variants:
            variant_to_canonical[normalize(v)] = canonical
    return variant_to_canonical


def resolve_companies(records, alias_path=None):
    """records: list of dicts, each with a 'winner_name' key (raw string) and
    other award-record fields. Returns a dict keyed by canonical company id
    -> {"display_name", "variants": set, "records": [...]}.
    """
    variant_overrides = load_aliases(alias_path) if alias_path else {}
    groups = {}
    for rec in records:
        raw_name = rec.get("winner_name")
        if not raw_name:
            continue
        norm = normalize(raw_name)
        if norm in variant_overrides:
            canonical_key = variant_overrides[norm]
        elif len(norm) < MIN_NORMALIZED_LENGTH:
            canonical_key = f"raw:{raw_name.strip().lower()}"
        else:
            canonical_key = norm
        if canonical_key not in groups:
            groups[canonical_key] = {
                "display_name": raw_name,
                "variants": set(),
                "records": [],
            }
        group = groups[canonical_key]
        group["variants"].add(raw_name)
        group["records"].append(rec)
        # Prefer the shortest observed variant as the display name — usually
        # the cleanest form (fewer legal-suffix duplications / typos).
        if len(raw_name) < len(group["display_name"]):
            group["display_name"] = raw_name
    return groups


def summarize(groups):
    """Turn resolve_companies() output into the aggregated view the
    dashboard reads: one row per company with totals and variant list.

    Sums `total_value_eur`, which ted_fetch.py populates by converting each
    record's original-currency value to EUR at the ECB reference rate for
    its notice date — records in mismatched currencies can't be summed
    directly, so this field must already be currency-normalized.
    """
    companies = []
    for key, group in groups.items():
        total_value_eur = 0.0
        priced_contracts = 0
        for rec in group["records"]:
            value_eur = rec.get("total_value_eur")
            if value_eur is None:
                continue
            total_value_eur += value_eur
            priced_contracts += 1
        companies.append(
            {
                "id": key,
                "display_name": group["display_name"],
                "variants": sorted(group["variants"]),
                "contract_count": len(group["records"]),
                "priced_contract_count": priced_contracts,
                "total_value_eur": round(total_value_eur, 2),
                "records": group["records"],
            }
        )
    companies.sort(key=lambda c: c["total_value_eur"], reverse=True)
    return companies
