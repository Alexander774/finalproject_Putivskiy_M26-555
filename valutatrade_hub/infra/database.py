"""Singleton JSON database with atomic per-file writes."""

import json
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader


class StorageError(Exception):
    """Raised when JSON data cannot be loaded or saved."""


class DatabaseManager:
    """Provide one shared JSON persistence gateway per Python process."""

    _instance: "DatabaseManager | None" = None
    _instance_lock = threading.Lock()
    _transaction_lock = threading.RLock()

    def __new__(cls) -> "DatabaseManager":
        # __new__ avoids a metaclass and keeps calls DatabaseManager() simple.
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Protect a read-modify-write sequence within this Python process.

        RLock also permits load/save methods to be called inside the transaction.
        This is not a cross-process or multi-file ACID transaction.
        """
        with self._transaction_lock:
            yield

    def _read(self, key: str, default: Any) -> Any:
        with self._transaction_lock:
            path = SettingsLoader().data_file(key)
            try:
                contents = path.read_text(encoding="utf-8")
                # A fully empty file is equivalent to an uninitialized store.
                if not contents.strip():
                    return default
                return json.loads(contents)
            except FileNotFoundError:
                return default
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                # Malformed NONEMPTY JSON must not be silently overwritten.
                raise StorageError(f"Не удалось прочитать {path.name}: {exc}") from exc

    def _write(self, key: str, data: Any) -> None:
        with self._transaction_lock:
            path = SettingsLoader().data_file(key)
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
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def load_users(self) -> list[dict[str, Any]]:
        """Return the list of user records."""
        records = self._read("users_file", [])
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise StorageError("users.json должен содержать список пользователей")
        return records

    def save_users(self, records: list[dict[str, Any]]) -> None:
        """Persist user records."""
        self._write("users_file", records)

    def load_portfolios(self) -> list[dict[str, Any]]:
        """Return the list of portfolio records."""
        records = self._read("portfolios_file", [])
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise StorageError("portfolios.json должен содержать список портфелей")
        return records

    def save_portfolios(self, records: list[dict[str, Any]]) -> None:
        """Persist portfolio records."""
        self._write("portfolios_file", records)

    def load_rates(self) -> dict[str, Any]:
        """Return cached exchange rates and metadata."""
        records = self._read("rates_file", {})
        if not isinstance(records, dict):
            raise StorageError("Неверный формат rates.json")
        return records

    def save_rates(self, records: dict[str, Any]) -> None:
        """Persist cached exchange rates and metadata."""
        self._write("rates_file", records)
