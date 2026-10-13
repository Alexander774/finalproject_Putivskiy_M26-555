"""Decorators for non-intrusive structured action logging."""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypeVar

from valutatrade_hub.logging_config import configure_logging

ReturnT = TypeVar("ReturnT")


def log_action(
    action: str, *, verbose: bool = False
) -> Callable[[Callable[..., ReturnT]], Callable[..., ReturnT]]:
    """Log every success and failure while preserving the exception.

    Passwords and password hashes are never included in the log fields.
    """

    def decorate(func: Callable[..., ReturnT]) -> Callable[..., ReturnT]:
        signature = inspect.signature(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> ReturnT:
            bound = signature.bind_partial(*args, **kwargs)
            arguments = bound.arguments
            app = arguments.get("self")
            current_user = getattr(app, "_current_user", None)
            username = (
                arguments.get("username")
                if action.upper() in {"LOGIN", "REGISTER"}
                else getattr(current_user, "username", None)
            ) or "-"
            currency = arguments.get("currency_code", "-")
            if isinstance(currency, str):
                currency = currency.upper()
            amount = arguments.get("amount")
            fields = [
                datetime.now(UTC).isoformat(),
                action.upper(),
                f"user={username!r}",
            ]
            if currency != "-":
                fields.append(f"currency={currency!r}")
            if "from_currency" in arguments:
                fields.append(f"from={arguments['from_currency']!r}")
            if "to_currency" in arguments:
                fields.append(f"to={arguments['to_currency']!r}")
            if action.upper() in {"BUY", "SELL"}:
                fields.append("base='USD'")
            elif "to_currency" in arguments:
                fields.append(f"base={arguments['to_currency']!r}")
            if amount is not None:
                fields.append(f"amount={amount!r}")
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                fields.extend(
                    (
                        "result=ERROR",
                        f"error_type={type(exc).__name__}",
                        f"error_message={str(exc)!r}",
                    )
                )
                configure_logging().info(" ".join(fields))
                raise
            else:
                rate = getattr(result, "rate", None)
                if rate is not None:
                    fields.append(f"rate={rate:.8g}")
                if verbose and hasattr(result, "before"):
                    fields.append(f"before={result.before:.8f}")
                    fields.append(f"after={result.after:.8f}")
                fields.append("result=OK")
                configure_logging().info(" ".join(fields))
                return result

        return wrapper

    return decorate
