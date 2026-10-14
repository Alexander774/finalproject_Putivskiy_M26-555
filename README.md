# ValutaTrade Hub

ValutaTrade Hub — консольное приложение на Python для отслеживания курсов фиатных и криптовалют и симуляции торговли в виртуальном портфеле.

Приложение получает цены криптовалют через **CoinGecko**, а курсы фиатных валют — через **ExchangeRate-API**. Курсы кешируются локально в JSON-файлах, поэтому для каждой операции с портфелем не требуется новый запрос к API.

## Возможности

- Регистрация пользователей и вход в систему
- Виртуальные кошельки для USD, EUR, GBP, RUB, BTC, ETH и SOL
- Покупка и продажа виртуальных единиц валют
- Оценка стоимости портфеля в выбранной базовой валюте
- Ручное обновление курсов, фильтрация кеша и получение обменных курсов
- История курсов, обработка ошибок и ротация логов

## Установка и запуск

Требуются **Python 3.12+** и [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Создайте файл `.env` в корне проекта:

```dotenv
COINGECKO_API_KEY=ваш_ключ_coingecko
EXCHANGERATE_API_KEY=ваш_ключ_exchangerate
```

Получить ключи можно на сайтах [CoinGecko](https://www.coingecko.com/en/api) и [ExchangeRate-API](https://www.exchangerate-api.com/). Не добавляйте файл `.env` в Git.

Запустите приложение:

```bash
uv run --env-file .env valutatrade
```

## Пример работы с CLI

```text
update-rates
show-rates --top 2
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
show-portfolio --base USD
sell --currency BTC --amount 0.01
get-rate --from BTC --to USD
show-rates --currency EUR
exit
```

Для просмотра доступных команд введите `help`.

## Структура проекта

- `valutatrade_hub/core/` — модели данных и торговые операции
- `valutatrade_hub/cli/` — командный интерфейс
- `valutatrade_hub/parser_service/` — API-клиенты, обновление курсов и управление кешем
- `valutatrade_hub/infra/` — конфигурация и хранение данных в JSON
- `data/` — данные пользователей и портфелей, кеш и история курсов

Время актуальности кеша настраивается (по умолчанию — 300 секунд). Если курсы отсутствуют или устарели, выполните `update-rates`. Курсы можно обновлять сразу из обоих источников или из выбранного.

## Разработка

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

## Демонстрация

[![asciicast](https://asciinema.org/a/A6e4FORzNMdTyNqu.svg)](https://asciinema.org/a/A6e4FORzNMdTyNqu)

> **Учебный проект.** Сделки изменяют только виртуальные балансы: при покупке USD не списываются, а при продаже не начисляются. Приложение не совершает реальных финансовых операций.
