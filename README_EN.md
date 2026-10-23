<p align="right">
  <a href="README.md">
    <img src="https://img.shields.io/badge/语言-中文-red?style=for-the-badge" alt="中文 README" />
  </a>
</p>

# Stock Market Simulator v2

A purely recreational, stress-free A-share trading simulator. This is the rewritten version of the [original project](legacy/README_EN.md). The original ran entirely in the browser; v2 splits it into a **FastAPI backend** and a **Vite frontend**, adding accounts, multiple saves, server-side market progression and real-time WebSocket updates.

All market data is generated locally. No real market feed is contacted, so you can learn trading rules, experience volatility and test strategies without any financial risk.

---

## Features

- Multiple saves and accounts; saves can be exported and imported (legacy export text is supported)
- Market and limit orders, ±10% daily price limits, T+1 settlement (T+0 can be enabled), trading lots of 1 or 100 shares
- Deterministic market: the same save produces the same results whenever it is replayed; ticks missed while away are computed on return
- Auto-trading rules, achievements, candlestick charts and order book
- Chinese and English UI, light and dark themes

## Quick Start

### Option 1: Docker Compose (recommended)

Requires Docker with Docker Compose v2.

```bash
cp .env.example .env
docker compose up -d --build
```

Open <http://localhost:18000>. Change the port with `FRONTEND_PORT` in `.env`.

Stop the stack:

```bash
docker compose down
```

### Option 2: Local development with hot reload

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 22 and `make`.

```bash
make dev
```

- Frontend: <http://localhost:5173>
- Backend API docs: <http://127.0.0.1:8000/docs>

A containerised dev stack is also available:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Run `make help` to list every target.

## Switching Databases

By default the app uses SQLite, stored in the `backend-data` volume with no extra service. To use PostgreSQL or MySQL:

| Database | Command | `DATABASE_URL` in `.env` |
| --- | --- | --- |
| SQLite (default) | `docker compose up -d --build` | `sqlite:////data/stocksim.db` |
| PostgreSQL | `docker compose --profile postgres up -d --build` | `postgresql+psycopg://stocksim:change-me@postgres:5432/stocksim` |
| MySQL | `docker compose --profile mysql up -d --build` | `mysql+pymysql://stocksim:change-me@mysql:3306/stocksim?charset=utf8mb4` |

Key points:

1. Change both the `--profile` flag and `DATABASE_URL` in `.env`.
2. A new database starts empty and migrations run automatically. To move saves from an old database, export them first and import them afterwards.
3. After editing `.env`, run `up` again so containers pick up the new values.

See the [deployment guide](docs/deployment.md) for details (in Chinese).

## Project Structure

| Path | Description |
| --- | --- |
| `backend/` | FastAPI backend (managed by uv, package `stocksim`), with Alembic migrations |
| `frontend/` | Vite frontend, native ES modules |
| `docs/` | Architecture, deployment, contract and ADRs |
| `scripts/` | Repository helper scripts (currently empty) |
| `legacy/` | Original front-end code (read-only, used as reference) |
| `docker-compose.yml` | Production-like stack: migrate → backend → frontend, optional postgres / mysql |
| `docker-compose.dev.yml` | Development overlay with source mounts and hot reload |
| `.env.example` | Environment variable template |
| `Makefile` | Common commands: `make dev`, `make test`, `make lint`, `make up`, and more |
| `.github/workflows/ci.yml` | CI: backend ruff + pytest, Alembic smoke test, frontend build and tests |

Each directory has a `CLAUDE.md` (boundaries for AI agents) and a `README.md` (for humans).

## Documentation

- [Architecture](docs/architecture.md) (Chinese)
- [Deployment](docs/deployment.md) (Chinese)
- [Contract](docs/CONTRACT.md) (Chinese)
- [Architecture Decision Records](docs/adr/README.md)

## Developer Notes

- Amounts are stored and transmitted as integer cents; field names end with `_cents`.
- Any change to a database model must include an Alembic migration.
- API changes must be reflected in `frontend/src/api`.
- Backend tests: `cd backend && uv run pytest`. Frontend build: `cd frontend && npm run build`.

## Credits and License

Original author: 莫客星图 (Bilibili). See [LICENSE](LICENSE) for the license.
