"""Cached currency conversion backed by a temporary demo provider."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from valutatrade_hub.infra.storage import load_rates, save_rates
from valutatrade_hub.parser_service.config import CACHE_TTL, DEMO_RATES_USD


class RateUnavailableError(Exception):
    """Raised when the requested currency is unsupported."""


@dataclass(frozen=True)
class RateQuote:
    """Price of one unit of the source currency in the target currency."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime


class RateService:
    """Get cross-rates from the local USD cache or demo provider."""

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Return one unit of from_currency priced in to_currency."""
        source_rate, source_time = self._usd_rate(from_currency)
        target_rate, target_time = self._usd_rate(to_currency)
        return RateQuote(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=source_rate / target_rate,
            updated_at=min(source_time, target_time),
        )

    def _usd_rate(self, code: str) -> tuple[float, datetime]:
        now = datetime.now(UTC)
        if code == "USD":
            return 1.0, now

        cached_rates = load_rates()
        key = f"{code}_USD"
        cached_entry = cached_rates.get(key)

        if isinstance(cached_entry, dict):
            cached = self._parse_entry(cached_entry)
            if cached is not None:
                rate, timestamp = cached
                if timestamp <= now and now - timestamp < CACHE_TTL:
                    return rate, timestamp

        fresh_rate = DEMO_RATES_USD.get(code)
        if fresh_rate is None:
            raise RateUnavailableError(f"Курс для {code}→USD недоступен")

        cached_rates[key] = {
            "rate": fresh_rate,
            "updated_at": now.isoformat(),
        }
        cached_rates["source"] = "DemoParser"
        cached_rates["last_refresh"] = now.isoformat()
        save_rates(cached_rates)
        return fresh_rate, now

    @staticmethod
    def _parse_entry(entry: dict[str, Any]) -> tuple[float, datetime] | None:
        rate = entry.get("rate")
        timestamp = entry.get("updated_at")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            return None
        if rate <= 0 or not math.isfinite(rate):
            return None
        if not isinstance(timestamp, str):
            return None
        try:
            updated_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return float(rate), updated_at
