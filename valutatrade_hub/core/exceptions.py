"""User-facing exceptions for currency and trading operations."""


class InsufficientFundsError(ValueError):
    """Raised when the requested amount exceeds the wallet balance."""

    def __init__(self, available: float, required: float, code: str) -> None:
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.8f} {code}, "
            f"требуется {required:.8f} {code}"
        )


class CurrencyNotFoundError(ValueError):
    """Raised when a currency is absent from the supported registry."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(RuntimeError):
    """Raised when the rate provider cannot supply a quote."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
