"""Read-only Core Service rate lookups from the parser-owned JSON cache."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.storage import RatesStorage, parse_timestamp

RateUnavailableError = ApiRequestError


@dataclass(frozen=True, slots=True)
class RateQuote:
    """Value of one source unit in target currency units."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CachedRate:
    """One cache row, including freshness and provider metadata."""

    pair: str
    rate: float
    updated_at: datetime
    source: str
    is_fresh: bool


@dataclass(frozen=True, slots=True)
class RatesTable:
    """Rates converted to the requested base for the CLI."""

    base_currency: str
    last_refresh: str | None
    rows: tuple[CachedRate, ...]


class RateService:
    """Convert currencies using cache only; never silently invent prices."""

    def __init__(self, storage: RatesStorage | None = None) -> None:
        self._storage = storage if storage is not None else RatesStorage()
        self._settings = SettingsLoader()

    def _entry(
        self, snapshot: dict[str, Any], code: str
    ) -> tuple[float, datetime, bool, str]:
        """Return USD rate, provider timestamp, TTL validity and provider."""
        now = datetime.now(UTC)
        if code == "USD":
            return 1.0, now, True, "BaseCurrency"

        pair = f"{code}_USD"
        entry = snapshot["pairs"].get(pair)
        if not isinstance(entry, dict):
            raise ApiRequestError(
                f"Курс {code}→USD отсутствует в кеше. Выполните update-rates"
            )
        rate = entry.get("rate")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
        ):
            raise ApiRequestError(f"Некорректный курс {pair} в кеше")
        try:
            updated = parse_timestamp(entry["updated_at"])
            # FX provider timestamps are typically refreshed daily. TTL
            # applies to fetch time, not the original market-data timestamp.
            fetched = parse_timestamp(entry.get("fetched_at", entry["updated_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiRequestError(f"Некорректное время курса {pair} в кеше") from exc
        age = now - fetched
        is_fresh = (
            timedelta(0)
            <= age
            < timedelta(seconds=self._settings.get("rates_ttl_seconds"))
        )
        return float(rate), updated, is_fresh, str(entry.get("source", "Unknown"))

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Calculate a cross-rate using only fresh cached observations."""
        source = get_currency(from_currency).code
        target = get_currency(to_currency).code
        if source == target:
            return RateQuote(source, target, 1.0, datetime.now(UTC))
        snapshot = self._storage.load_snapshot()
        from_rate, from_time, from_fresh, _ = self._entry(snapshot, source)
        to_rate, to_time, to_fresh, _ = self._entry(snapshot, target)
        if not from_fresh or not to_fresh:
            raise ApiRequestError("Кеш курсов устарел. Выполните update-rates")
        return RateQuote(
            from_currency=source,
            to_currency=target,
            rate=from_rate / to_rate,
            updated_at=min(from_time, to_time),
        )

    def show_rates(
        self,
        *,
        currency: str | None = None,
        top: int | None = None,
        base: str = "USD",
    ) -> RatesTable:
        """Read local snapshot, optionally filter and convert displayed rows."""
        target = get_currency(base).code
        if top is not None and (isinstance(top, bool) or top <= 0):
            raise ValueError("'top' должен быть положительным целым числом")
        code_filter = currency.upper() if currency else None
        snapshot = self._storage.load_snapshot()
        if not snapshot["pairs"]:
            return RatesTable(target, snapshot.get("last_refresh"), ())

        base_rate, _, base_fresh, _ = self._entry(snapshot, target)
        rows: list[CachedRate] = []
        for pair in sorted(snapshot["pairs"]):
            if not pair.endswith("_USD"):
                continue
            code = pair.removesuffix("_USD")
            if code_filter and code != code_filter:
                continue
            try:
                currency_info = get_currency(code)
                if top is not None and not isinstance(currency_info, CryptoCurrency):
                    continue
                rate, updated, fresh, source = self._entry(snapshot, code)
            except (ValueError, ApiRequestError):
                # Unknown legacy codes and malformed cache rows are excluded.
                continue
            rows.append(
                CachedRate(
                    f"{code}_{target}",
                    rate / base_rate,
                    updated,
                    source,
                    fresh and base_fresh,
                )
            )

        if top is not None:
            rows.sort(key=lambda row: row.rate, reverse=True)
            rows = rows[:top]
        return RatesTable(target, snapshot.get("last_refresh"), tuple(rows))
