"""Interactive terminal interface for currency operations."""

import argparse
import shlex

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.usecases import TradingApp, UseCaseError
from valutatrade_hub.infra.database import StorageError
from valutatrade_hub.logging_config import configure_logging


def _build_parser() -> argparse.ArgumentParser:
    """Describe supported commands and their arguments."""
    parser = argparse.ArgumentParser(
        prog="valutatrade",
        description="Виртуальная торговля валютами (реальный локальный кеш).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="Зарегистрироваться")
    register.add_argument("--username", required=True)
    register.add_argument("--password", required=True)

    login = commands.add_parser("login", help="Войти")
    login.add_argument("--username", required=True)
    login.add_argument("--password", required=True)

    portfolio = commands.add_parser("show-portfolio", help="Показать портфель")
    portfolio.add_argument("--base", default=None)

    for command in ("buy", "sell"):
        trade = commands.add_parser(command, help=f"Операция {command}")
        trade.add_argument("--currency", required=True)
        trade.add_argument("--amount", required=True, type=float)

    rate = commands.add_parser(
        "get-rate",
        help="Показать курс",
        description="Курс берётся только из локального кеша Parser Service.",
    )
    rate.add_argument("--from", dest="from_currency", required=True)
    rate.add_argument("--to", dest="to_currency", required=True)

    update = commands.add_parser("update-rates", help="Обновить курсы через API")
    update.add_argument("--source", choices=("coingecko", "exchangerate"))

    show_rates = commands.add_parser("show-rates", help="Показать кеш курсов")
    show_rates.add_argument("--currency")
    show_rates.add_argument("--top", type=int)
    show_rates.add_argument("--base", default="USD")
    return parser


def _format_rate(rate: float) -> str:
    """Display ordinary rates without scientific notation."""
    if 1e-10 <= rate < 1_000_000:
        return f"{rate:.12f}".rstrip("0").rstrip(".")
    return f"{rate:.12g}"


def _execute(args: argparse.Namespace, app: TradingApp) -> None:
    """Dispatch a parsed command to the application service."""
    if args.command == "register":
        user = app.register(args.username, args.password)
        print(f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}).")
        print("Войдите с помощью login.")

    elif args.command == "login":
        user = app.login(args.username, args.password)
        print(f"Вы вошли как '{user.username}'")

    elif args.command == "show-portfolio":
        summary = app.show_portfolio(args.base)
        print(
            f"Портфель пользователя '{summary.username}' "
            f"(база: {summary.base_currency}):"
        )
        if not summary.rows:
            print("В портфеле пока нет кошельков.")
            return
        table = PrettyTable()
        table.field_names = ["Валюта", "Баланс", f"В {summary.base_currency}"]
        for row in summary.rows:
            table.add_row(
                [row.currency_code, f"{row.balance:.8f}", f"{row.value:,.2f}"]
            )
        print(table)
        print(f"ИТОГО: {summary.total:,.2f} {summary.base_currency}")

    elif args.command in {"buy", "sell"}:
        operation = app.buy if args.command == "buy" else app.sell
        result = operation(args.currency, args.amount)
        title = "Покупка" if args.command == "buy" else "Продажа"
        amount_label = "стоимость покупки" if args.command == "buy" else "выручка"
        print(
            f"{title} выполнена: {result.amount:.8f} {result.currency_code} "
            f"по курсу {result.rate:,.8f} USD/{result.currency_code}"
        )
        print(
            f"Баланс: {result.before:.8f} → {result.after:.8f} {result.currency_code}"
        )
        print(f"Оценочная {amount_label}: {result.usd_value:,.2f} USD")

    elif args.command == "get-rate":
        quote = app.get_rate(args.from_currency, args.to_currency)
        timestamp = quote.updated_at.strftime("%Y-%m-%d %H:%M:%S %Z")
        print(
            f"Курс {quote.from_currency}→{quote.to_currency}: "
            f"{_format_rate(quote.rate)} (обновлено: {timestamp})"
        )
        print(
            f"Обратный курс {quote.to_currency}→{quote.from_currency}: "
            f"{_format_rate(1 / quote.rate)}"
        )
        print("Источник: локальный кеш Parser Service")

    elif args.command == "update-rates":
        result = app.update_rates(
            args.source,
            progress_callback=lambda level, message: print(f"{level}: {message}"),
        )
        if result.partial_failure:
            print(
                "Обновление частично завершено. Ошибки: "
                + ", ".join(result.failed_sources)
            )
            print("Подробности: logs/parser.log")
        else:
            print("Обновление успешно завершено.")
        print(f"Обновлено курсов: {result.updated_count}.")
        print(f"Последнее обновление: {result.last_refresh}")

    elif args.command == "show-rates":
        if args.top is not None and args.top <= 0:
            raise UseCaseError("'top' должен быть положительным целым числом")
        summary = app.show_rates(args.currency, args.top, args.base)
        if not summary.rows:
            if args.currency:
                print(f"Курс для '{args.currency.upper()}' не найден в кеше.")
            else:
                print("Локальный кеш курсов пуст. Выполните 'update-rates'.")
            return
        print(f"Курсы из кеша (last_refresh: {summary.last_refresh}):")
        table = PrettyTable()
        table.field_names = ["Пара", "Курс", "Обновлено (UTC)", "Источник", "Статус"]
        for row in summary.rows:
            table.add_row(
                [
                    row.pair,
                    _format_rate(row.rate),
                    row.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                    row.source,
                    "актуален" if row.is_fresh else "устарел",
                ]
            )
        print(table)
        if any(not row.is_fresh for row in summary.rows):
            print("Часть курсов устарела. Выполните 'update-rates'.")


def _print_command_error(error: Exception) -> None:
    """Present domain and infrastructure errors without leaking tracebacks."""
    if isinstance(error, InsufficientFundsError):
        print(error)
    elif isinstance(error, CurrencyNotFoundError):
        print(f"{error}. Поддерживаемые коды: {', '.join(get_supported_codes())}.")
        print("Справка: help get-rate")
    elif isinstance(error, ApiRequestError):
        print(f"{error}. Повторите попытку позже или проверьте сеть.")
    elif isinstance(error, UseCaseError):
        # The use case already contains a complete user-facing message.
        print(error)
    else:
        print(f"Ошибка: {error}")


def main() -> None:
    """Run the persistent interactive command loop."""
    parser = _build_parser()
    configure_logging()
    app = TradingApp()
    print("ValutaTrade Hub. Введите help для команд, exit для выхода.")

    while True:
        try:
            command_line = input("valutatrade> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            break

        if not command_line:
            continue
        if command_line.lower() in {"exit", "quit"}:
            print("До свидания!")
            break
        if command_line.lower() == "help":
            parser.print_help()
            continue
        if command_line.lower().startswith("help "):
            name = command_line.split(maxsplit=1)[1].strip()
            commands = {
                "register",
                "login",
                "buy",
                "sell",
                "show-portfolio",
                "get-rate",
                "update-rates",
                "show-rates",
            }
            if name in commands:
                try:
                    parser.parse_args([name, "--help"])
                except SystemExit:
                    pass
            else:
                print(f"Неизвестная команда: {name}")
            continue

        try:
            args = parser.parse_args(shlex.split(command_line))
            _execute(args, app)
        except SystemExit:
            # argparse uses SystemExit for --help and invalid arguments.
            continue
        except (
            InsufficientFundsError,
            CurrencyNotFoundError,
            ApiRequestError,
            UseCaseError,
            StorageError,
            ValueError,
            TypeError,
        ) as exc:
            _print_command_error(exc)
