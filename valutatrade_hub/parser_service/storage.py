"""Atomic JSON persistence for the rate snapshot and observation history."""

import math
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from valutatrade_hub.infra.database import DatabaseManager, StorageError
from valutatrade_hub.parser_service.api_clients import RateObservation

_PAIR = re.compile(r"[A-Z0-9]{2,5}_[A-Z0-9]{2,5}\Z")


def utc_timestamp(value: datetime) -> str:
    """Format a timezone-aware datetime as an ISO UTC timestamp."""
    if value.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp; reject missing timezone information."""
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid ISO timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return timestamp.astimezone(UTC)


def validate_observation(observation: RateObservation) -> None:
    """Reject malformed pairs, timestamps and invalid prices before writing."""
    if not isinstance(observation, RateObservation):
        raise TypeError("Expected RateObservation")
    if not _PAIR.fullmatch(observation.pair):
        raise ValueError(f"Invalid currency pair: {observation.pair}")
    if (
        isinstance(observation.rate, bool)
        or not isinstance(observation.rate, (int, float))
        or not math.isfinite(observation.rate)
        or observation.rate <= 0
    ):
        raise ValueError(f"Invalid rate for {observation.pair}")
    parse_timestamp(observation.timestamp)
    if not observation.source or not isinstance(observation.source, str):
        raise ValueError("Observation must include a source")


class RatesStorage:
    """Merge fresh snapshots and append unique records to the history.

    Atomicity is per JSON file. The RLock covers two-file read/modify/write
    sequences only inside one Python process, not independent processes.
    """

    def __init__(self, database: DatabaseManager | None = None) -> None:
        self.database = database if database is not None else DatabaseManager()

    def load_snapshot(self) -> dict[str, Any]:
        """Return a normalized snapshot, accepting the old flat cache format."""
        snapshot = self.database.load_rates()
        if "pairs" in snapshot:
            if not isinstance(snapshot["pairs"], dict):
                raise StorageError("rates.json: поле pairs должно быть объектом")
            return snapshot

        # Migration from legacy {"BTC_USD": {...}, "source": ...}.
        source = snapshot.get("source", "LegacyCache")
        pairs: dict[str, Any] = {}
        for key, entry in snapshot.items():
            if not _PAIR.fullmatch(key) or not isinstance(entry, dict):
                continue
            pairs[key] = {
                **entry,
                "source": entry.get("source", source),
                "fetched_at": entry.get("fetched_at", entry.get("updated_at")),
            }
        return {"pairs": pairs, "last_refresh": snapshot.get("last_refresh")}

    def save_observations(
        self,
        observations: list[RateObservation],
        *,
        fetched_at: datetime | None = None,
    ) -> int:
        """Save validated observations; return count of refreshed cache pairs.

        Existing newer quotes win. An equal provider timestamp with the same
        value renews the local fetch time without duplicating history.
        """
        normalized: list[RateObservation] = []
        for observation in observations:
            validate_observation(observation)
            canonical = utc_timestamp(parse_timestamp(observation.timestamp))
            normalized.append(replace(observation, timestamp=canonical))
        if not normalized:
            return 0
        when = utc_timestamp(fetched_at or datetime.now(UTC))

        with self.database.transaction():
            snapshot = self.load_snapshot()
            pairs = snapshot["pairs"]
            history = self.database.load_rate_history()
            known_ids = {entry.get("id") for entry in history}
            refreshed = 0

            for observation in normalized:
                if observation.record_id not in known_ids:
                    history.append(observation.to_history_record())
                    known_ids.add(observation.record_id)

                old = pairs.get(observation.pair)
                should_replace = True
                if isinstance(old, dict):
                    try:
                        old_time = parse_timestamp(old["updated_at"])
                        new_time = parse_timestamp(observation.timestamp)
                        if old_time > new_time:
                            should_replace = False
                        elif (
                            old_time == new_time and old.get("rate") != observation.rate
                        ):
                            should_replace = False
                    except (KeyError, ValueError, TypeError):
                        pass
                if should_replace:
                    pairs[observation.pair] = {
                        "rate": float(observation.rate),
                        "updated_at": observation.timestamp,
                        "fetched_at": when,
                        "source": observation.source,
                    }
                    refreshed += 1

            snapshot["last_refresh"] = when
            # Persist history first: a snapshot never points to an
            # observation that was not first durably recorded in history.
            self.database.save_rate_history(history)
            self.database.save_rates(snapshot)
            return refreshed
