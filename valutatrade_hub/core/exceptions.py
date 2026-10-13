"""Domain-specific exceptions for ValutaTrade Hub."""


class CurrencyNotFoundError(ValueError):
    """Raised when a valid currency code is absent from the registry."""
