# ValutaTrade Hub: CLI implementation (section 2.2)

Copy the six new Python files from the `valutatrade_hub/` folder into the
identically named directories in your existing project. Your existing
`valutatrade_hub/core/models.py` is deliberately **not** included or changed.

## Prerequisites

The existing project must contain the `User`, `Wallet`, `Portfolio` classes
from the previous stage. `core/usecases.py` uses the internal helper functions
`_validate_currency_code` and `_validate_number` from that version.

Make sure `pyproject.toml` includes:

```toml
[project.scripts]
valutatrade = "valutatrade_hub.cli.interface:main"
```

and that `prettytable` is a runtime dependency (`uv add prettytable`).

Initialize data files (or leave existing JSON files intact):

- `data/users.json`: `[]`
- `data/portfolios.json`: `[]`
- `data/rates.json`: `{}`

Run from project root:

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run valutatrade
```

Example commands inside the **same interactive CLI process**:

```text
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
show-portfolio --base USD
sell --currency BTC --amount 0.01
get-rate --from USD --to BTC
exit
```

## Known scope limitations

- According to section 2.2, a simulated `buy` credits the purchased currency
  without deducting USD, and `sell` deducts holdings without crediting USD.
  Thus the displayed cash consideration is indicative, not settled.
- Rates are static demonstration values, not live market data.
- Authenticated session persists **only during the current CLI process**.
- Password hashing uses salted SHA-256 as required by the educational brief;
  use a dedicated slow password-hashing algorithm in real applications.
- The storage layer writes individual JSON files atomically, but transactions
  across users.json and portfolios.json are not atomic.
