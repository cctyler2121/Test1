"""ECB daily reference exchange rates, for converting award values in local
currency (DKK, SEK, PLN, ...) to EUR — the same convention the source TED
dashboard uses ("financials converted to euros at ECB rates").
"""
import csv
import io
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

ECB_HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"


def download_rates(url=ECB_HIST_URL, timeout=60):
    """Returns {date_str "YYYY-MM-DD": {currency_code: rate_vs_eur}}.
    Rate is "units of currency per 1 EUR" (ECB's convention), so
    amount_in_eur = amount_in_currency / rate.
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
    text = zf.read(csv_name).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rates = {}
    for row in reader:
        d = row.get("Date", "").strip()
        if not d:
            continue
        day_rates = {}
        for currency, value in row.items():
            if currency == "Date" or not value:
                continue
            value = value.strip()
            if not value or value == "N/A":
                continue
            try:
                day_rates[currency.strip()] = float(value)
            except ValueError:
                continue
        rates[d] = day_rates
    return rates


class RateTable:
    def __init__(self, rates_by_date):
        self.rates_by_date = rates_by_date
        self.sorted_dates = sorted(rates_by_date)

    def rate_on_or_before(self, currency, target_date_str, max_lookback_days=10):
        """ECB doesn't publish on weekends/holidays, so walk backwards up to
        max_lookback_days to find the most recent available rate."""
        try:
            target = datetime.strptime(target_date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
        for offset in range(max_lookback_days + 1):
            d = (target - timedelta(days=offset)).isoformat()
            day_rates = self.rates_by_date.get(d)
            if day_rates and currency in day_rates:
                return day_rates[currency]
        return None

    def to_eur(self, amount, currency, notice_date_str):
        if currency is None or amount is None:
            return None
        if currency == "EUR":
            return amount
        rate = self.rate_on_or_before(currency, notice_date_str)
        if rate is None or rate == 0:
            return None
        return amount / rate
