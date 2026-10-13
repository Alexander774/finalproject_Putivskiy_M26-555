"""Application operations, independent of terminal input and output."""

from dataclasses import dataclass
from datetime import datetime

from valutatrade_hub.core.models import (
    Portfolio,
    User,
    Wallet,
    _validate_currency_code,
    _validate_number,
)
from valutatrade_hub.infra.storage import (
    StorageError,
    load_portfolios,
    load_users,
    save_portfolios,
    save_users,
)
from valutatrade_hub.parser_service.parser import (
    RateQuote,
    RateService,
    RateUnavailableError,
)


class UseCaseError(Exception):
    """Raised for an expected application-level error."""


@dataclass(frozen=True)
class PortfolioRow:
    """Balance and its value in the requested currency."""

    currency_code: str
    balance: float
    value: float


@dataclass(frozen=True)
class PortfolioSummary:
    """A portfolio prepared for presentation by any user interface."""

    username: str
    base_currency: str
    rows: list[PortfolioRow]
    total: float


@dataclass(frozen=True)
class TradeResult:
    """Completed simulated operation and its indicative USD price."""

    currency_code: str
    amount: float
    before: float
    after: float
    rate: float
    usd_value: float


class TradingApp:
    """Coordinate users, portfolios, session state and rate lookups."""

    def __init__(self, rate_service: RateService | None = None) -> None:
        self._current_user: User | None = None
        self._rates = rate_service or RateService()

    def register(self, username: str, password: str) -> User:
        """Register a unique user and create their empty portfolio."""
        if not isinstance(username, str) or not username.strip():
            raise UseCaseError("Пустое имя пользователя")

        username = username.strip()
        users = load_users()
        if any(
            str(item.get("username", "")).casefold() == username.casefold()
            for item in users
        ):
            raise UseCaseError(f"Имя '{username}' уже занято")

        user_id = max((int(item["user_id"]) for item in users), default=0) + 1
        try:
            user = User.create(user_id, username, password)
        except (TypeError, ValueError) as exc:
            raise UseCaseError("Пароль должен быть не короче 4 символов") from exc

        portfolios = load_portfolios()
        users.append(
            {
                "user_id": user.user_id,
                "username": user.username,
                "hashed_password": user.hashed_password,
                "salt": user.salt,
                "registration_date": user.registration_date.isoformat(),
            }
        )
        portfolios.append({"user_id": user.user_id, "wallets": {}})
        save_users(users)
        save_portfolios(portfolios)
        return user

    def login(self, username: str, password: str) -> User:
        """Authenticate the user for the lifetime of the CLI process."""
        users = load_users()
        record = next((row for row in users if row.get("username") == username), None)
        if record is None:
            raise UseCaseError(f"Пользователь '{username}' не найден")

        user = self._decode_user(record)
        if not user.verify_password(password):
            raise UseCaseError("Неверный пароль")

        self._current_user = user
        return user

    def show_portfolio(self, base_currency: str = "USD") -> PortfolioSummary:
        """Return every balance and its total value in base currency."""
        user = self._require_login()
        base = _validate_currency_code(base_currency)
        portfolio = self._load_portfolio(user)

        try:
            base_usd = self._rates.get_rate(base, "USD").rate
        except RateUnavailableError as exc:
            raise UseCaseError(f"Неизвестная базовая валюта '{base}'") from exc

        rates_usd = {base: base_usd}
        rows: list[PortfolioRow] = []
        for code, wallet in sorted(portfolio.wallets.items()):
            try:
                usd_rate = self._rates.get_rate(code, "USD").rate
            except RateUnavailableError as exc:
                raise UseCaseError(f"Нет курса для валюты '{code}'") from exc
            rates_usd[code] = usd_rate
            rows.append(
                PortfolioRow(code, wallet.balance, wallet.balance * usd_rate / base_usd)
            )

        total = portfolio.get_total_value(base, exchange_rates=rates_usd)
        return PortfolioSummary(user.username, base, rows, total)

    def buy(self, currency_code: str, amount: float) -> TradeResult:
        """Credit purchased units without debiting USD (section 2.2)."""
        user = self._require_login()
        code = _validate_currency_code(currency_code)
        amount = self._positive_amount(amount)
        quote = self._usd_quote(code)
        portfolio = self._load_portfolio(user)

        try:
            wallet = portfolio.get_wallet(code)
        except KeyError:
            wallet = portfolio.add_currency(code)

        before = wallet.balance
        wallet.deposit(amount)
        self._save_portfolio(portfolio)
        return TradeResult(
            code, amount, before, wallet.balance, quote.rate, amount * quote.rate
        )

    def sell(self, currency_code: str, amount: float) -> TradeResult:
        """Deduct units without crediting USD (section 2.2)."""
        user = self._require_login()
        code = _validate_currency_code(currency_code)
        amount = self._positive_amount(amount)
        portfolio = self._load_portfolio(user)

        try:
            wallet = portfolio.get_wallet(code)
        except KeyError as exc:
            raise UseCaseError(
                f"У вас нет кошелька '{code}'. Он создаётся при первой покупке."
            ) from exc

        if wallet.balance < amount:
            raise UseCaseError(
                f"Недостаточно средств: {wallet.balance:.8f} {code} доступно; "
                f"требуется {amount:.8f} {code}"
            )

        quote = self._usd_quote(code)
        before = wallet.balance
        wallet.withdraw(amount)
        self._save_portfolio(portfolio)
        return TradeResult(
            code, amount, before, wallet.balance, quote.rate, amount * quote.rate
        )

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Get a cross-rate, without requiring authentication."""
        source = _validate_currency_code(from_currency)
        target = _validate_currency_code(to_currency)
        try:
            return self._rates.get_rate(source, target)
        except RateUnavailableError as exc:
            raise UseCaseError(
                f"Курс {source}→{target} недоступен. Повторите попытку позже."
            ) from exc

    @staticmethod
    def _decode_user(record: dict) -> User:
        try:
            return User(
                user_id=record["user_id"],
                username=record["username"],
                hashed_password=record["hashed_password"],
                salt=record["salt"],
                registration_date=datetime.fromisoformat(record["registration_date"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError("Некорректная запись пользователя в users.json") from exc

    def _require_login(self) -> User:
        if self._current_user is None:
            raise UseCaseError("Сначала выполните login")
        return self._current_user

    @staticmethod
    def _positive_amount(amount: float) -> float:
        try:
            return _validate_number(amount, positive=True)
        except (TypeError, ValueError) as exc:
            raise UseCaseError("'amount' должен быть положительным числом") from exc

    def _usd_quote(self, currency_code: str) -> RateQuote:
        try:
            return self._rates.get_rate(currency_code, "USD")
        except RateUnavailableError as exc:
            raise UseCaseError(
                f"Не удалось получить курс для {currency_code}→USD"
            ) from exc

    def _load_portfolio(self, user: User) -> Portfolio:
        record = next(
            (row for row in load_portfolios() if row.get("user_id") == user.user_id),
            None,
        )
        if record is None:
            return Portfolio(user)
        try:
            wallets = {
                code: Wallet(code, contents["balance"])
                for code, contents in record["wallets"].items()
            }
            return Portfolio(user, wallets)
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise StorageError("Некорректный портфель в portfolios.json") from exc

    @staticmethod
    def _save_portfolio(portfolio: Portfolio) -> None:
        portfolios = load_portfolios()
        new_record = {
            "user_id": portfolio.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in portfolio.wallets.items()
            },
        }
        for index, record in enumerate(portfolios):
            if record.get("user_id") == portfolio.user_id:
                portfolios[index] = new_record
                break
        else:
            portfolios.append(new_record)
        save_portfolios(portfolios)
