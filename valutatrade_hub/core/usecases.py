"""Application operations, independent of terminal input and output."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.models import Portfolio, User, Wallet, _validate_number
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager, StorageError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.parser import RateQuote, RateService, RatesTable
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater, UpdateResult


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
        self._settings = SettingsLoader()
        self._db = DatabaseManager()
        self._rates = rate_service if rate_service is not None else RateService()

    @log_action("REGISTER")
    def register(self, username: str, password: str) -> User:
        """Register a unique user and create a matching empty portfolio.

        Read both stores before writing either. If the second save fails,
        restore the original users file as a compensating rollback.
        """
        if not isinstance(username, str) or not username.strip():
            raise UseCaseError("Пустое имя пользователя")

        username = username.strip()
        with self._db.transaction():
            users = self._db.load_users()
            portfolios = self._db.load_portfolios()
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

            original_users = users.copy()
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

            self._db.save_users(users)
            try:
                self._db.save_portfolios(portfolios)
            except StorageError as exc:
                try:
                    self._db.save_users(original_users)
                except StorageError as rollback_exc:
                    raise StorageError(
                        "Регистрация прервана: не удалось восстановить users.json "
                        f"после ошибки сохранения portfolios.json: {rollback_exc}"
                    ) from exc
                raise

            return user

    @log_action("LOGIN")
    def login(self, username: str, password: str) -> User:
        """Authenticate the user for the lifetime of the CLI process."""
        users = self._db.load_users()
        record = next((row for row in users if row.get("username") == username), None)
        if record is None:
            raise UseCaseError(f"Пользователь '{username}' не найден")

        user = self._decode_user(record)
        if not user.verify_password(password):
            raise UseCaseError("Неверный пароль")

        self._current_user = user
        return user

    def show_portfolio(self, base_currency: str | None = None) -> PortfolioSummary:
        """Return every balance and its total value in base currency."""
        user = self._require_login()
        base = get_currency(
            base_currency or self._settings.get("default_base_currency")
        ).code
        portfolio = self._load_portfolio(user)
        base_usd = self._rates.get_rate(base, "USD").rate

        rates_usd = {base: base_usd}
        rows: list[PortfolioRow] = []
        for code, wallet in sorted(portfolio.wallets.items()):
            usd_rate = self._rates.get_rate(code, "USD").rate
            rates_usd[code] = usd_rate
            rows.append(
                PortfolioRow(code, wallet.balance, wallet.balance * usd_rate / base_usd)
            )

        total = portfolio.get_total_value(base, exchange_rates=rates_usd)
        return PortfolioSummary(user.username, base, rows, total)

    @log_action("BUY", verbose=True)
    def buy(self, currency_code: str, amount: float) -> TradeResult:
        """Credit currency units, saving the wallet only after success."""
        user = self._require_login()
        code = get_currency(currency_code).code
        amount = self._positive_amount(amount)
        # Never create an empty wallet if the requested rate is unavailable.
        quote = self._rates.get_rate(code, "USD")

        with self._db.transaction():
            records = self._db.load_portfolios()
            portfolio = self._load_portfolio(user, records)
            try:
                wallet = portfolio.get_wallet(code)
            except KeyError:
                wallet = portfolio.add_currency(code)

            before = wallet.balance
            wallet.deposit(amount)
            self._save_portfolio(portfolio, records)
            return TradeResult(
                code, amount, before, wallet.balance, quote.rate, amount * quote.rate
            )

    @log_action("SELL", verbose=True)
    def sell(self, currency_code: str, amount: float) -> TradeResult:
        """Withdraw currency units, rejecting missing or insufficient funds."""
        user = self._require_login()
        code = get_currency(currency_code).code
        amount = self._positive_amount(amount)

        with self._db.transaction():
            records = self._db.load_portfolios()
            portfolio = self._load_portfolio(user, records)
            try:
                wallet = portfolio.get_wallet(code)
            except KeyError as exc:
                raise UseCaseError(
                    f"У вас нет кошелька '{code}'. Он создаётся при первой покупке."
                ) from exc

            if wallet.balance < amount:
                raise InsufficientFundsError(wallet.balance, amount, code)

            # Obtain the price before changing any balance.
            quote = self._rates.get_rate(code, "USD")
            before = wallet.balance
            wallet.withdraw(amount)
            self._save_portfolio(portfolio, records)
            return TradeResult(
                code, amount, before, wallet.balance, quote.rate, amount * quote.rate
            )

    @log_action("GET_RATE")
    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Get a cross-rate, without requiring authentication."""
        source = get_currency(from_currency).code
        target = get_currency(to_currency).code
        return self._rates.get_rate(source, target)

    def update_rates(
        self,
        source: str | None = None,
        *,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> UpdateResult:
        """Refresh all or a selected provider without requiring login."""
        if source not in {None, "coingecko", "exchangerate"}:
            raise UseCaseError("Источник должен быть coingecko или exchangerate")
        config = ParserConfig()
        clients = []
        if source in {None, "coingecko"}:
            clients.append(CoinGeckoClient(config))
        if source in {None, "exchangerate"}:
            clients.append(ExchangeRateApiClient(config))
        updater = RatesUpdater(
            clients, RatesStorage(self._db), progress_callback=progress_callback
        )
        return updater.run_update()

    def show_rates(
        self,
        currency: str | None = None,
        top: int | None = None,
        base: str | None = None,
    ) -> RatesTable:
        """Return current cached pairs for table display without HTTP calls."""
        return self._rates.show_rates(
            currency=currency,
            top=top,
            base=base or self._settings.get("default_base_currency"),
        )

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

    def _load_portfolio(
        self, user: User, records: list[dict] | None = None
    ) -> Portfolio:
        """Deserialize a user's wallet collection from loaded JSON records."""
        if records is None:
            records = self._db.load_portfolios()
        record = next(
            (row for row in records if row.get("user_id") == user.user_id), None
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

    def _save_portfolio(
        self, portfolio: Portfolio, records: list[dict] | None = None
    ) -> None:
        """Replace a user's record and persist all portfolios together."""
        if records is None:
            records = self._db.load_portfolios()
        new_record = {
            "user_id": portfolio.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in portfolio.wallets.items()
            },
        }
        for index, record in enumerate(records):
            if record.get("user_id") == portfolio.user_id:
                records[index] = new_record
                break
        else:
            records.append(new_record)
        self._db.save_portfolios(records)
