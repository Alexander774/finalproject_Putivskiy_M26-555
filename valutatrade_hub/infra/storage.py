"""Compatibility wrappers around the Singleton DatabaseManager API."""

from typing import Any

from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.database import StorageError as StorageError


def load_users() -> list[dict[str, Any]]:
    """Load the registered users."""
    return DatabaseManager().load_users()


def save_users(records: list[dict[str, Any]]) -> None:
    """Save the registered users."""
    DatabaseManager().save_users(records)


def load_portfolios() -> list[dict[str, Any]]:
    """Load portfolio records."""
    return DatabaseManager().load_portfolios()


def save_portfolios(records: list[dict[str, Any]]) -> None:
    """Save portfolio records."""
    DatabaseManager().save_portfolios(records)


def load_rates() -> dict[str, Any]:
    """Load the rate cache."""
    return DatabaseManager().load_rates()


def save_rates(records: dict[str, Any]) -> None:
    """Save the rate cache."""
    DatabaseManager().save_rates(records)
