"""Read and write JSON storage without domain-specific logic."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import PORTFOLIOS_FILE, RATES_FILE, USERS_FILE


class StorageError(Exception):
    """Raised when persistent JSON data cannot be read or saved."""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Не удалось прочитать {path.name}: {exc}") from exc


def _write_json(path: Path, data: Any) -> None:
    """Atomically replace one JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as exc:
        raise StorageError(f"Не удалось сохранить {path.name}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_users() -> list[dict[str, Any]]:
    """Load user records."""
    data = _read_json(USERS_FILE, [])
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise StorageError("users.json должен содержать список пользователей")
    return data


def save_users(users: list[dict[str, Any]]) -> None:
    """Persist user records."""
    _write_json(USERS_FILE, users)


def load_portfolios() -> list[dict[str, Any]]:
    """Load portfolio records."""
    data = _read_json(PORTFOLIOS_FILE, [])
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise StorageError("portfolios.json должен содержать список портфелей")
    return data


def save_portfolios(portfolios: list[dict[str, Any]]) -> None:
    """Persist portfolio records."""
    _write_json(PORTFOLIOS_FILE, portfolios)


def load_rates() -> dict[str, Any]:
    """Load the cached exchange-rate records."""
    data = _read_json(RATES_FILE, {})
    if not isinstance(data, dict):
        raise StorageError("Неверный формат rates.json")
    return data


def save_rates(rates: dict[str, Any]) -> None:
    """Persist cached exchange rates."""
    _write_json(RATES_FILE, rates)
