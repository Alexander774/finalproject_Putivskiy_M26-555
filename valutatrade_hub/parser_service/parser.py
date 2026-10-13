"""Cached currency conversion backed by a temporary demo provider."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.config import DEMO_RATES_USD

# Compatibility alias for code using the previous error name.
RateUnavailableError = ApiRequestError


@dataclass(frozen=True)
class RateQuote:
    """Price of one source unit in target units."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime


class RateService:
    """Get cross-rates from the local USD cache or demo provider."""

    def __init__(self) -> None:
        self._settings = SettingsLoader()
        self._db = DatabaseManager()

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Return one unit of from_currency priced in to_currency."""
        source = get_currency(from_currency).code
        target = get_currency(to_currency).code
        source_rate, source_time = self._usd_rate(source)
        target_rate, target_time = self._usd_rate(target)
        return RateQuote(
            from_currency=source,
            to_currency=target,
            rate=source_rate / target_rate,
            updated_at=min(source_time, target_time),
        )

    def _usd_rate(self, code: str) -> tuple[float, datetime]:
        now = datetime.now(UTC)
        if code == "USD":
            return 1.0, now

        cached_rates = self._db.load_rates()
        cached_entry = cached_rates.get(f"{code}_USD")
        if isinstance(cached_entry, dict):
            cached = self._parse_entry(cached_entry)
            if cached is not None:
                rate, timestamp = cached
                ttl = timedelta(seconds=self._settings.get("rates_ttl_seconds"))
                if timestamp <= now and now - timestamp < ttl:
                    return rate, timestamp

        # The real parser/HTTP request will replace this demo provider.
        fresh_rate = DEMO_RATES_USD.get(code)
        if fresh_rate is None:
            raise ApiRequestError(f"нет доступного курса для {code}→USD")

        cached_rates[f"{code}_USD"] = {
            "rate": fresh_rate,
            "updated_at": now.isoformat(),
        }
        cached_rates["source"] = "DemoParser"
        cached_rates["last_refresh"] = now.isoformat()
        self._db.save_rates(cached_rates)
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
