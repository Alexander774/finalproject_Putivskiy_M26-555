"""Interactive terminal interface for currency operations."""

import argparse
import shlex

from prettytable import PrettyTable

from valutatrade_hub.core.usecases import TradingApp, UseCaseError
from valutatrade_hub.infra.storage import StorageError


def _build_parser() -> argparse.ArgumentParser:
    """Describe supported commands and their arguments."""
    parser = argparse.ArgumentParser(prog="valutatrade")
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="Зарегистрироваться")
    register.add_argument("--username", required=True)
    register.add_argument("--password", required=True)

    login = commands.add_parser("login", help="Войти")
    login.add_argument("--username", required=True)
    login.add_argument("--password", required=True)

    portfolio = commands.add_parser("show-portfolio", help="Показать портфель")
    portfolio.add_argument("--base", default="USD")

    for command in ("buy", "sell"):
        trade = commands.add_parser(command, help=f"Операция {command}")
        trade.add_argument("--currency", required=True)
        trade.add_argument("--amount", required=True, type=float)

    rate = commands.add_parser("get-rate", help="Показать курс")
    rate.add_argument("--from", dest="from_currency", required=True)
    rate.add_argument("--to", dest="to_currency", required=True)
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
        print("Источник: кеш или демонстрационные курсы (не рыночные данные)")


def main() -> None:
    """Run the persistent interactive command loop."""
    parser = _build_parser()
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

        try:
            args = parser.parse_args(shlex.split(command_line))
            _execute(args, app)
        except SystemExit:
            # argparse uses SystemExit for --help and invalid arguments.
            continue
        except (UseCaseError, StorageError, ValueError, TypeError) as exc:
            print(f"Ошибка: {exc}")
