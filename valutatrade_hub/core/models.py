"""Domain models for users and virtual currency portfolios."""

import hashlib
import hmac
import math
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import InsufficientFundsError

# Temporary illustrative rates: value of one unit in USD.
# Actual rates will later come from the parser service.
DEMO_RATES_USD: dict[str, float] = {
    "EUR": 1.10,
    "GBP": 1.25,
    "BTC": 60_000.0,
    "ETH": 3_000.0,
}


def _validate_currency_code(currency_code: str) -> str:
    """Return a normalized currency code or reject an invalid one."""
    if not isinstance(currency_code, str):
        raise TypeError("Currency code must be a string")

    code = currency_code.strip().upper()

    if not code or not code.isascii() or not code.isalnum():
        raise ValueError("Currency code must contain only Latin letters and digits")

    return code


def _validate_number(value: int | float, *, positive: bool) -> float:
    """Validate a finite, nonnegative or strictly positive amount."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Amount must be an int or float, not bool")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError("Amount must be finite")

    if number < 0 or (positive and number == 0):
        if positive:
            raise ValueError("Amount must be positive")
        raise ValueError("Amount cannot be negative")

    return number


class User:
    """Registered user with a salted password hash."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise TypeError("User ID must be an integer")
        if user_id <= 0:
            raise ValueError("User ID must be positive")

        if not isinstance(hashed_password, str) or not hashed_password:
            raise ValueError("Password hash must be a nonempty string")

        if not isinstance(salt, str) or not salt:
            raise ValueError("Salt must be a nonempty string")

        if not isinstance(registration_date, datetime):
            raise TypeError("Registration date must be a datetime")

        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Create a user with a generated salt and password hash."""
        cls._validate_password(password)

        salt = secrets.token_hex(16)
        hashed_password = cls._hash_password(password, salt)

        return cls(
            user_id=user_id,
            username=username,
            hashed_password=hashed_password,
            salt=salt,
            registration_date=datetime.now(UTC),
        )

    @staticmethod
    def _validate_password(password: str) -> None:
        """Check that a new password meets the length requirement."""
        if not isinstance(password, str):
            raise TypeError("Password must be a string")

        if len(password) < 4:
            raise ValueError("Password must contain at least 4 characters")

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Compute the educational SHA-256 password hash."""
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    @property
    def user_id(self) -> int:
        """Return the immutable user identifier."""
        return self._user_id

    @property
    def username(self) -> str:
        """Return the username."""
        return self._username

    @username.setter
    def username(self, new_username: str) -> None:
        if not isinstance(new_username, str):
            raise TypeError("Username must be a string")

        new_username = new_username.strip()

        if not new_username:
            raise ValueError("Username cannot be empty")

        self._username = new_username

    @property
    def hashed_password(self) -> str:
        """Return the password hash for persistent storage."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Return the password salt for persistent storage."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Return the registration timestamp."""
        return self._registration_date

    def get_user_info(self) -> dict[str, int | str]:
        """Return user information without password credentials."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Replace the password hash and generate a new salt."""
        self._validate_password(new_password)
        self._salt = secrets.token_hex(16)
        self._hashed_password = self._hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Check whether a password matches the stored hash."""
        if not isinstance(password, str):
            raise TypeError("Password must be a string")

        candidate = self._hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._hashed_password)


class Wallet:
    """Wallet containing a balance in a single currency."""

    def __init__(
        self,
        currency_code: str,
        balance: float = 0.0,
    ) -> None:
        self.currency_code = _validate_currency_code(currency_code)
        self.balance = balance

    @property
    def balance(self) -> float:
        """Return the current balance."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = _validate_number(value, positive=False)

    def deposit(self, amount: float) -> None:
        """Increase the balance by a positive amount."""
        amount = _validate_number(amount, positive=True)
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Withdraw a positive amount or raise InsufficientFundsError."""
        amount = _validate_number(amount, positive=True)

        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)

        self.balance -= amount

    def get_balance_info(self) -> dict[str, str | float]:
        """Return the currency code and current balance."""
        return {
            "currency_code": self.currency_code,
            "balance": self.balance,
        }


class Portfolio:
    """Collection of currency wallets belonging to one user."""

    def __init__(
        self,
        user: User,
        wallets: dict[str, Wallet] | None = None,
    ) -> None:
        if not isinstance(user, User):
            raise TypeError("Portfolio user must be a User instance")

        self._user = user
        self._user_id = user.user_id
        self._wallets: dict[str, Wallet] = {}

        if wallets is not None:
            if not isinstance(wallets, dict):
                raise TypeError("Wallets must be a dictionary")

            for currency_code, wallet in wallets.items():
                code = _validate_currency_code(currency_code)

                if not isinstance(wallet, Wallet):
                    raise TypeError("Each wallet must be a Wallet instance")

                if code != wallet.currency_code:
                    raise ValueError("Wallet key does not match its currency code")

                if code in self._wallets:
                    raise ValueError(f"Duplicate currency code: {code}")

                self._wallets[code] = wallet

    @property
    def user_id(self) -> int:
        """Return the portfolio owner's identifier."""
        return self._user_id

    @property
    def user(self) -> User:
        """Return the portfolio owner without allowing reassignment."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Return a shallow copy of the wallets dictionary."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        """Create an empty wallet, rejecting duplicate currencies."""
        code = _validate_currency_code(currency_code)

        if code in self._wallets:
            raise ValueError(f"Wallet already exists: {code}")

        wallet = Wallet(code)
        self._wallets[code] = wallet

        return wallet

    def get_wallet(self, currency_code: str) -> Wallet:
        """Return a wallet by currency code, or raise KeyError."""
        code = _validate_currency_code(currency_code)
        return self._wallets[code]

    def get_total_value(
        self,
        base_currency: str = "USD",
        exchange_rates: Mapping[str, float] | None = None,
    ) -> float:
        """Calculate portfolio value using USD-denominated rates.

        Exchange rates represent the USD price of one currency unit.
        USD has an implicit rate of 1.
        """
        base_currency = _validate_currency_code(base_currency)

        rates = DEMO_RATES_USD if exchange_rates is None else exchange_rates

        if not isinstance(rates, Mapping):
            raise TypeError("Exchange rates must be a mapping")

        def rate_in_usd(currency_code: str) -> float:
            if currency_code == "USD":
                return 1.0

            try:
                value = rates[currency_code]
            except KeyError as exc:
                raise ValueError(f"Missing exchange rate for {currency_code}") from exc

            return _validate_number(value, positive=True)

        total_usd = sum(
            wallet.balance * rate_in_usd(wallet.currency_code)
            for wallet in self._wallets.values()
            if wallet.balance > 0
        )

        return total_usd / rate_in_usd(base_currency)
