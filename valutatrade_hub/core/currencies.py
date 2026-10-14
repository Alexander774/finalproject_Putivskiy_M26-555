"""Currency hierarchy and a factory for supported currencies."""

import math
import re
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

_CURRENCY_CODE_PATTERN = re.compile(r"[A-Z0-9]{2,5}")


def _validate_text(value: str, field_name: str) -> str:
    """Validate a required text attribute without changing its contents."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value


def _normalize_code(code: str) -> str:
    """Normalize letter case and enforce the currency-code format."""
    if not isinstance(code, str):
        raise TypeError("Currency code must be a string")

    normalized = code.upper()
    if _CURRENCY_CODE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            "Currency code must be 2-5 uppercase Latin letters or digits, "
            "without spaces"
        )
    return normalized


class Currency(ABC):
    """Abstract base class describing a currency."""

    def __init__(self, name: str, code: str) -> None:
        self.name = _validate_text(name, "Currency name")
        self.code = _normalize_code(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Return currency information formatted for the CLI and logs."""


class FiatCurrency(Currency):
    """Government-issued currency with an issuing country or zone."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        self.issuing_country = _validate_text(issuing_country, "Issuing country")

    def get_display_info(self) -> str:
        """Return fiat-currency information in the required format."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Cryptocurrency with an algorithm label and market capitalization."""

    def __init__(
        self,
        name: str,
        code: str,
        algorithm: str,
        market_cap: float,
    ) -> None:
        super().__init__(name, code)
        self.algorithm = _validate_text(algorithm, "Algorithm")
        if isinstance(market_cap, bool) or not isinstance(market_cap, (int, float)):
            raise TypeError("Market cap must be a number")
        if not math.isfinite(market_cap) or market_cap < 0:
            raise ValueError("Market cap must be a finite nonnegative number")
        self.market_cap = float(market_cap)

    def get_display_info(self) -> str:
        """Return cryptocurrency information with a compact market cap."""
        cap = f"{self.market_cap:.2e}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {cap})"
        )


# Illustrative registry entries. Market capitalizations are NOT live data.
_FIAT_CURRENCIES: dict[str, tuple[str, str]] = {
    "USD": ("US Dollar", "United States"),
    "EUR": ("Euro", "Eurozone"),
    "GBP": ("Pound Sterling", "United Kingdom"),
    "RUB": ("Russian Ruble", "Russia"),
}

_CRYPTO_CURRENCIES: dict[str, tuple[str, str, float]] = {
    "BTC": ("Bitcoin", "SHA-256", 1.12e12),
    "ETH": ("Ether", "Keccak-256", 3.00e11),
    "SOL": ("Solana", "Proof of History", 7.00e10),
}


def get_currency(code: str) -> Currency:
    """Create a known currency or raise CurrencyNotFoundError."""
    normalized = _normalize_code(code)

    if normalized in _FIAT_CURRENCIES:
        name, issuing_country = _FIAT_CURRENCIES[normalized]
        return FiatCurrency(name, normalized, issuing_country)

    if normalized in _CRYPTO_CURRENCIES:
        name, algorithm, market_cap = _CRYPTO_CURRENCIES[normalized]
        return CryptoCurrency(name, normalized, algorithm, market_cap)

    raise CurrencyNotFoundError(normalized)


def get_supported_codes() -> tuple[str, ...]:
    """Return all currency codes supported by the built-in registry."""
    return tuple(sorted(_FIAT_CURRENCIES.keys() | _CRYPTO_CURRENCIES.keys()))
