"""HTTP clients for CoinGecko and ExchangeRate-API.

``fetch_rates()`` offers the common minimal contract (pair -> float).
``fetch_observations()`` retains the metadata needed by the future updater.
No client writes JSON files or logs secrets.
"""

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig


def _iso_utc(value: datetime) -> str:
    """Serialize an aware UTC timestamp with seconds precision."""
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _unix_timestamp(value: Any, provider: str) -> str:
    """Decode a positive Unix second timestamp supplied by an API."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiRequestError(f"{provider}: некорректный timestamp")
    try:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Nonpositive or nonfinite timestamp")
        return _iso_utc(datetime.fromtimestamp(value, tz=UTC))
    except (OverflowError, OSError, ValueError) as exc:
        raise ApiRequestError(f"{provider}: некорректный timestamp") from exc


def _positive_rate(value: Any, pair: str) -> float:
    """Reject missing, non-finite, non-numeric or nonpositive exchange rates."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiRequestError(f"Некорректный курс {pair}: ожидалось число")
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0:
        raise ApiRequestError(f"Некорректный курс {pair}: значение <= 0 или нечисловое")
    return rate


@dataclass(frozen=True, slots=True)
class RateObservation:
    """One validated one-way quote with provider metadata."""

    from_currency: str
    to_currency: str
    rate: float
    timestamp: str
    source: str
    meta: dict[str, Any]

    @property
    def pair(self) -> str:
        """Return the canonical pair key, e.g. BTC_USD."""
        return f"{self.from_currency}_{self.to_currency}"

    @property
    def record_id(self) -> str:
        """Return the reproducible pair-and-source-timestamp identifier."""
        return f"{self.pair}_{self.timestamp}"

    def to_history_record(self) -> dict[str, Any]:
        """Build a history document compatible with exchange_rates.json."""
        return {
            "id": self.record_id,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate": self.rate,
            "timestamp": self.timestamp,
            "source": self.source,
            "meta": self.meta.copy(),
        }


class BaseApiClient(ABC):
    """Uniform external-rate provider protocol."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config if config is not None else ParserConfig()
        self._last_observations: tuple[RateObservation, ...] = ()

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Return valid rates as FROM_TO -> quote in TO per 1 FROM."""

    @abstractmethod
    def fetch_observations(self) -> list[RateObservation]:
        """Return the same quotes with timestamps and HTTP metadata."""

    @property
    def last_observations(self) -> tuple[RateObservation, ...]:
        """Metadata from the latest fetch_rates call, without another HTTP request."""
        return self._last_observations

    def _get_json(
        self,
        url: str,
        *,
        provider: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Perform one bounded HTTP GET and sanitize failures.

        ExchangeRate-API embeds a secret in the URL: exception messages must
        NOT include the URL or the original RequestException string.
        """
        start = time.perf_counter()
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.request_timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise ApiRequestError(
                f"{provider}: сетевая ошибка ({type(exc).__name__})"
            ) from exc

        request_ms = round((time.perf_counter() - start) * 1000)
        if response.status_code != 200:
            raise ApiRequestError(f"{provider}: HTTP {response.status_code}")
        try:
            data = response.json()
        except (ValueError, requests.exceptions.RequestException) as exc:
            raise ApiRequestError(f"{provider}: некорректный JSON в ответе") from exc
        if not isinstance(data, dict):
            raise ApiRequestError(f"{provider}: ответ должен быть JSON-объектом")
        return data, {
            "request_ms": request_ms,
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }


class CoinGeckoClient(BaseApiClient):
    """Fetch USD (or another configured base) crypto quotations."""

    def fetch_rates(self) -> dict[str, float]:
        """Return crypto prices as BTC_USD -> 59337.21, etc."""
        observations = self.fetch_observations()
        self._last_observations = tuple(observations)
        return {observation.pair: observation.rate for observation in observations}

    def fetch_observations(self) -> list[RateObservation]:
        """Fetch crypto quotes with CoinGecko coin IDs and source timestamps."""
        config = self.config
        try:
            ids = [config.crypto_id_map[code] for code in config.crypto_currencies]
        except KeyError as exc:
            raise ApiRequestError(
                f"CoinGecko: нет ID для валюты {exc.args[0]}"
            ) from exc

        headers = {"Accept": "application/json"}
        if config.coingecko_api_key:
            headers["x-cg-demo-api-key"] = config.coingecko_api_key

        data, request_meta = self._get_json(
            config.coingecko_url,
            provider="CoinGecko",
            params={
                "ids": ",".join(ids),
                "vs_currencies": config.base_currency.lower(),
                "include_last_updated_at": "true",
            },
            headers=headers,
        )
        now = _iso_utc(datetime.now(UTC))
        observations: list[RateObservation] = []
        for code, coin_id in zip(config.crypto_currencies, ids, strict=True):
            details = data.get(coin_id)
            if not isinstance(details, dict):
                raise ApiRequestError(f"CoinGecko: нет данных для {code} ({coin_id})")
            pair = f"{code}_{config.base_currency}"
            rate = _positive_rate(details.get(config.base_currency.lower()), pair)
            updated_at = details.get("last_updated_at")
            timestamp = (
                _unix_timestamp(updated_at, "CoinGecko")
                if updated_at is not None
                else now
            )
            observations.append(
                RateObservation(
                    from_currency=code,
                    to_currency=config.base_currency,
                    rate=rate,
                    timestamp=timestamp,
                    source="CoinGecko",
                    meta={**request_meta, "raw_id": coin_id},
                )
            )
        return observations


class ExchangeRateApiClient(BaseApiClient):
    """Fetch fiat prices, inverting USD-base conversion quotes as needed."""

    def fetch_rates(self) -> dict[str, float]:
        """Return fiat prices as EUR_USD -> 1.0787, etc."""
        observations = self.fetch_observations()
        self._last_observations = tuple(observations)
        return {observation.pair: observation.rate for observation in observations}

    def fetch_observations(self) -> list[RateObservation]:
        """Get foreign units per USD and convert to USD per foreign unit."""
        config = self.config
        if not config.exchangerate_api_key:
            raise ApiRequestError(
                "ExchangeRate-API: не задана переменная EXCHANGERATE_API_KEY"
            )
        url = (
            f"{config.exchangerate_api_url.rstrip('/')}/"
            f"{config.exchangerate_api_key}/latest/{config.base_currency}"
        )
        data, request_meta = self._get_json(
            url,
            provider="ExchangeRate-API",
            headers={"Accept": "application/json"},
        )
        if data.get("result") != "success":
            error_type = data.get("error-type")
            safe_types = {
                "unsupported-code",
                "malformed-request",
                "invalid-key",
                "inactive-account",
                "quota-reached",
            }
            reason = error_type if error_type in safe_types else "неуспешный ответ"
            raise ApiRequestError(f"ExchangeRate-API: {reason}")
        if data.get("base_code") != config.base_currency:
            raise ApiRequestError("ExchangeRate-API: неверная базовая валюта")

        # The actual v6 field is conversion_rates. Some course mocks use rates.
        conversion_rates = data.get("conversion_rates", data.get("rates"))
        if not isinstance(conversion_rates, dict):
            raise ApiRequestError("ExchangeRate-API: нет conversion_rates")

        update_unix = data.get("time_last_update_unix")
        if update_unix is not None:
            timestamp = _unix_timestamp(update_unix, "ExchangeRate-API")
        else:
            date_text = data.get("time_last_update_utc")
            if not isinstance(date_text, str):
                raise ApiRequestError("ExchangeRate-API: нет времени обновления")
            try:
                timestamp = _iso_utc(parsedate_to_datetime(date_text))
            except (ValueError, TypeError, IndexError) as exc:
                raise ApiRequestError(
                    "ExchangeRate-API: некорректное время обновления"
                ) from exc

        observations: list[RateObservation] = []
        for code in config.fiat_currencies:
            pair = f"{code}_{config.base_currency}"
            rate_from_base = _positive_rate(conversion_rates.get(code), pair)
            observations.append(
                RateObservation(
                    from_currency=code,
                    to_currency=config.base_currency,
                    rate=1.0 / rate_from_base,
                    timestamp=timestamp,
                    source="ExchangeRate-API",
                    meta=request_meta.copy(),
                )
            )
        return observations
