"""Coordinate multiple independent rate providers and persist their quotes."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import configure_parser_logging
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
    RateObservation,
)
from valutatrade_hub.parser_service.storage import (
    RatesStorage,
    utc_timestamp,
    validate_observation,
)

ProgressCallback = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """One parser update summary, including recoverable provider failures."""

    updated_count: int
    fetched_count: int
    last_refresh: str
    failed_sources: tuple[str, ...]

    @property
    def partial_failure(self) -> bool:
        """Whether at least one provider failed during this run."""
        return bool(self.failed_sources)


class RatesUpdater:
    """Fetch each provider once; merge, validate and persist the good quotes."""

    def __init__(
        self,
        clients: Sequence[BaseApiClient],
        storage: RatesStorage,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.clients = tuple(clients)
        self.storage = storage
        self.progress_callback = progress_callback
        self.logger = configure_parser_logging()

    @staticmethod
    def _source_name(client: BaseApiClient) -> str:
        if isinstance(client, CoinGeckoClient):
            return "CoinGecko"
        if isinstance(client, ExchangeRateApiClient):
            return "ExchangeRate-API"
        return getattr(client, "source", type(client).__name__)

    def _report(self, level: str, message: str) -> None:
        getattr(self.logger, level.lower())(message)
        if self.progress_callback:
            self.progress_callback(level, message)

    def run_update(self) -> UpdateResult:
        """Update available providers, continuing when any one API fails.

        All providers failing raises ApiRequestError without modifying JSON.
        Individual failures are returned in UpdateResult.failed_sources.
        """
        self._report("INFO", "Starting rates update...")
        observations: list[RateObservation] = []
        failed_sources: list[str] = []
        now = datetime.now(UTC)
        timestamp = utc_timestamp(now)

        for client in self.clients:
            source = self._source_name(client)
            self._report("INFO", f"Fetching from {source}...")
            try:
                # fetch_rates caches the metadata from this SAME HTTP request;
                # requesting fetch_observations again would consume API quota.
                rates = client.fetch_rates()
                if not isinstance(rates, dict) or not rates:
                    raise ApiRequestError(f"{source}: пустой или неверный ответ")
                metadata = {
                    item.pair: item for item in getattr(client, "last_observations", ())
                }
                valid_observations: list[RateObservation] = []
                for pair, rate in rates.items():
                    if not isinstance(pair, str) or "_" not in pair:
                        raise ApiRequestError(f"{source}: неверный код пары")
                    left, right = pair.split("_", maxsplit=1)
                    if (
                        isinstance(rate, bool)
                        or not isinstance(rate, (int, float))
                        or not math.isfinite(rate)
                        or rate <= 0
                    ):
                        raise ApiRequestError(f"{source}: неверный курс {pair}")
                    observation = metadata.get(pair) or RateObservation(
                        from_currency=left,
                        to_currency=right,
                        rate=float(rate),
                        timestamp=timestamp,
                        source=source,
                        meta={},
                    )
                    if observation.rate != rate:
                        raise ApiRequestError(
                            f"{source}: несогласованные данные {pair}"
                        )
                    validate_observation(observation)
                    valid_observations.append(observation)
            except Exception as exc:
                # A provider failure must not suppress healthy providers.
                # Unknown exceptions may contain URLs with credentials: only
                # trusted ApiRequestError messages can be logged verbatim.
                description = (
                    str(exc) if isinstance(exc, ApiRequestError) else type(exc).__name__
                )
                failed_sources.append(source)
                self._report("ERROR", f"Failed to fetch from {source}: {description}")
                continue

            observations.extend(valid_observations)
            self._report("INFO", f"Fetching from {source}... OK ({len(rates)} rates)")

        if not observations:
            self._report("ERROR", "Rates update failed: no provider returned rates")
            raise ApiRequestError("Все источники курсов недоступны. Повторите позже")

        self._report(
            "INFO", f"Writing up to {len(observations)} rates to rates.json..."
        )
        updated_count = self.storage.save_observations(observations, fetched_at=now)
        result = UpdateResult(
            updated_count=updated_count,
            fetched_count=len(observations),
            last_refresh=timestamp,
            failed_sources=tuple(failed_sources),
        )
        if failed_sources:
            self._report(
                "WARNING",
                f"Update completed with errors ({updated_count} rates refreshed).",
            )
        else:
            self._report(
                "INFO", f"Update successful ({updated_count} rates refreshed)."
            )
        return result
