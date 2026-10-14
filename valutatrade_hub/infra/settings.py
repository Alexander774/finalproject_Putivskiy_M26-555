"""Singleton configuration loader backed by [tool.valutatrade] in TOML."""

import threading
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "exchange_rates_file": "exchange_rates.json",
    "parser_log_file": "logs/parser.log",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_file": "logs/actions.log",
    "log_format": "text",
    "log_level": "INFO",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 3,
}


class SettingsLoader:
    """Share one configuration object throughout a single Python process.

    ``__new__`` is sufficient here: all callers must share one dictionary,
    and no class hierarchy needs a custom Singleton metaclass.
    """

    _instance: "SettingsLoader | None" = None
    _instance_lock = threading.Lock()
    _initialization_lock = threading.Lock()

    def __new__(cls) -> "SettingsLoader":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._values = _DEFAULTS.copy()
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if not self._initialized:
            with self._initialization_lock:
                if not self._initialized:
                    self.reload()
                    self._initialized = True

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configured value or the caller-provided fallback."""
        return self._values.get(key, default)

    def reload(self) -> None:
        """Reload values from pyproject.toml, falling back to defaults."""
        config_file = PROJECT_ROOT / "pyproject.toml"
        user_values: dict[str, Any] = {}
        if config_file.is_file():
            try:
                with config_file.open("rb") as file:
                    project = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ValueError("Не удалось загрузить pyproject.toml") from exc
            user_values = project.get("tool", {}).get("valutatrade", {})
            if not isinstance(user_values, dict):
                raise ValueError("[tool.valutatrade] должен быть таблицей")

        values = {**_DEFAULTS, **user_values}
        if (
            isinstance(values["rates_ttl_seconds"], bool)
            or not isinstance(values["rates_ttl_seconds"], int)
            or values["rates_ttl_seconds"] < 0
        ):
            raise ValueError("rates_ttl_seconds должен быть целым числом >= 0")
        if values["log_format"] != "text":
            raise ValueError("Поддерживается только log_format = 'text'")
        if values["log_level"] not in {"INFO", "DEBUG"}:
            raise ValueError("log_level должен быть INFO или DEBUG")
        for key in ("log_max_bytes", "log_backup_count"):
            if (
                isinstance(values[key], bool)
                or not isinstance(values[key], int)
                or values[key] < 0
            ):
                raise ValueError(f"{key} должен быть целым числом >= 0")
        self._values = values

    @property
    def data_dir(self) -> Path:
        """Return the absolute directory of JSON files."""
        return self._absolute(self.get("data_dir"))

    def data_file(self, key: str) -> Path:
        """Resolve a configured JSON filename within the data directory."""
        name = Path(self.get(key))
        return name if name.is_absolute() else self.data_dir / name

    @property
    def log_file(self) -> Path:
        """Return the absolute path of the action log file."""
        return self._absolute(self.get("log_file"))

    @staticmethod
    def _absolute(path: str) -> Path:
        result = Path(path)
        return result if result.is_absolute() else PROJECT_ROOT / result
