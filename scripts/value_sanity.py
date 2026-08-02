"""Sanity ceiling for a single award's EUR value, guarding against source
data-entry errors on TED's own side -- confirmed twice in production, not
a currency-conversion bug and not something this pipeline can correct
(there's no way to recover the intended real value from a garbage input):

- A Greek municipality's notice (239708-2026, buyer Dimos Dramas) quoted
  total-value = 1,073,062,200,000 EUR for what its CPV codes describe as
  routine security/IT equipment -- a single small-town contract worth more
  than the entire EU's annual GDP.
- A Polish notice (157377-2026) quoted total-value = 1,086,150,000,000 PLN
  (~EUR 253.99bn after correct currency conversion) for what its CPV codes
  describe as a routine fuel-supply contract, against the same winner's
  other ~70 contracts all in the hundreds-of-thousands-to-low-millions EUR
  range.

Both are internally consistent (currency conversion math checks out) --
the raw number TED itself reports is simply implausible, almost certainly
a data-entry error by whoever published the notice (extra digits, wrong
unit). This pipeline has no way to know the intended value, so rather than
guess or silently keep a number that would dominate every aggregate it
touches, values past this ceiling are excluded from sums -- the contract
itself still counts (contract_count, appears in listings with its raw
total_value/total_value_cur/notice_url intact so it can be checked
against the source), it's just not trusted as a EUR amount.
"""

# Set well above the largest verified-real notice found so far (~EUR
# 6.03bn, a Banedanmark/Rambøll framework re-tender -- see README's
# "Known limitations"), while well below the confirmed garbage values
# above (EUR 1.07 trillion, EUR 253.99bn).
MAX_PLAUSIBLE_VALUE_EUR = 50_000_000_000  # EUR 50bn


def sanitize_value_eur(value_eur):
    """Returns value_eur unchanged if plausible, else None -- treated
    identically to "no EUR value available" everywhere downstream
    (excluded from total_value_eur sums and priced_contract_count, but
    the record and its raw total_value/total_value_cur stay visible)."""
    if value_eur is not None and value_eur > MAX_PLAUSIBLE_VALUE_EUR:
        return None
    return value_eur
