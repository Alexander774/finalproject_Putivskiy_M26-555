"""Configuration for the external-currency parser.

Credentials are read from the process environment. For local development,
use ``uv run --env-file .env ...``; never commit the actual .env file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"
BASE_FIAT_CURRENCY = "USD"
FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}
REQUEST_TIMEOUT = 10.0

# Kept temporarily for compatibility with the previous offline RateService.
# These figures are fictional and MUST NOT be used as current quotations.
DEMO_RATES_USD: dict[str, float] = {
    "EUR": 1.10,
    "GBP": 1.25,
    "BTC": 60_000.0,
    "ETH": 3_000.0,
    "RUB": 0.01016,
}


@dataclass(frozen=True, slots=True)
class ParserConfig:
    """Hold API endpoints, tracked currencies, storage paths and credentials.

    Credential factories are evaluated at object creation rather than import.
    """

    exchangerate_api_key: str | None = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY"), repr=False
    )
    coingecko_api_key: str | None = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY"), repr=False
    )
    coingecko_url: str = COINGECKO_URL
    exchangerate_api_url: str = EXCHANGERATE_API_URL
    base_currency: str = BASE_FIAT_CURRENCY
    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES
    crypto_id_map: dict[str, str] = field(default_factory=lambda: dict(CRYPTO_ID_MAP))
    request_timeout: float = REQUEST_TIMEOUT

    @property
    def rates_file_path(self) -> Path:
        """Return the shared snapshot file used by Core Service."""
        return SettingsLoader().data_file("rates_file")

    @property
    def history_file_path(self) -> Path:
        """Return the Parser Service historical rates file."""
        settings = SettingsLoader()
        value = Path(settings.get("exchange_rates_file", "exchange_rates.json"))
        return value if value.is_absolute() else settings.data_dir / value
