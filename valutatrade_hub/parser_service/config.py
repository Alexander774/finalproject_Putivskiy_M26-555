"""Configuration for the temporary exchange-rate provider."""

from datetime import timedelta

CACHE_TTL = timedelta(minutes=5)

# Illustrative USD prices, not live market data.
DEMO_RATES_USD: dict[str, float] = {
    "EUR": 1.10,
    "GBP": 1.25,
    "BTC": 60_000.0,
    "ETH": 3_000.0,
    "RUB": 0.01016,
}
