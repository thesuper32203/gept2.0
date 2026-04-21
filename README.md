# GEPT 2.0 — OSRS Grand Exchange Flip Scanner

Collects real-time and historical price data from the Old School RuneScape Wiki API, stores it in a TimescaleDB database, and surfaces profitable flip opportunities using a rule-based scanner.

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/)

No Python installation required — everything runs inside Docker.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/thesuper32203/gept2.0.git
cd gept2.0
```

### 2. Configure environment variables

Create a `.env` file in the root directory:

```env
DB_NAME=postgres
DB_USER=postgres
DB_PASS=yourpassword
USER_AGENT=gept2.0-youremail@example.com
```

> **Note:** The `USER_AGENT` is required by the RuneScape Wiki API. Use your email or project name.

### 3. Start the application

```bash
docker-compose up --build
```

This will:
- Start a **TimescaleDB** database container
- Run the schema and create all tables automatically on first start
- Start the **collector** container which begins collecting price data

---

## What it collects

| Data | Frequency | Table |
|------|-----------|-------|
| Item metadata (names, alch values, buy limits) | Once at startup | `items` |
| 5-minute price snapshots | Every 5 minutes | `prices_5min` |
| 1-hour price snapshots | Every hour | `prices_1hr` |
| Historical backfill (last 90 days) | Once at startup | `prices_5min`, `prices_1hr` |

---

## Connecting to the database

Use any PostgreSQL client (e.g. DBeaver, TablePlus):

| Setting | Value |
|---------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `postgres` |
| Username | `postgres` |
| Password | *(your DB_PASS from .env)* |

In DBeaver, navigate to: **postgres → Schemas → public → Tables**

---

## Stopping the application

```bash
docker-compose down
```

To stop **and delete all data** (full reset):

```bash
docker-compose down -v
```

> Warning: `-v` permanently deletes the database volume and all collected data.

---

## Restarting after a stop

```bash
docker-compose up
```

The database persists between restarts unless `-v` was used.

---

## Project structure

```
gept2.0/
├── packages/
│   ├── collector/
│   │   ├── main.py                  # Entry point
│   │   ├── collectors/
│   │   │   ├── base.py              # Shared collection logic
│   │   │   ├── items.py             # Item metadata collector
│   │   │   ├── prices_5min.py       # 5-minute price collector
│   │   │   ├── prices_1hr.py        # 1-hour price collector
│   │   │   └── backfill.py          # Historical data backfill
│   │   └── db/
│   │       ├── connection.py        # Database connection pool
│   │       └── schema.sql           # Table definitions
│   └── engine/
│       ├── main.py                  # CLI entry point (--mode scan | --mode backtest)
│       ├── features/
│       │   └── builder.py           # Feature computation (spread, volume, rolling signals)
│       └── flipper/
│           ├── scanner.py           # Rule-based flip opportunity scanner
│           └── backtester.py        # Historical simulation and validation
├── docs/
│   ├── phase1/                      # Step-by-step Phase 1 guides
│   └── phase2/                      # Rule-based scanner build guide
├── Dockerfile
├── docker-compose.yml
└── .env                             # Your credentials (not committed)
```

## Running the scanner

```bash
# See current flip opportunities
python -m packages.engine.main --mode scan

# Validate scanner against 14 days of historical data
python -m packages.engine.main --mode backtest --days 14
```

---

## Troubleshooting

**No tables visible in database client**
The schema only runs when the database volume is first created. If the volume existed before setup, delete it and restart:
```bash
docker-compose down -v
docker-compose up --build
```

**Collector can't connect to database**
Ensure the `db` container is healthy before the collector starts. The `depends_on` healthcheck handles this automatically — if the collector crashes on startup, wait a moment and run `docker-compose up` again.

**DB_PASSWORD warning on startup**
This is a harmless Docker Compose warning. Ensure your `.env` file uses `DB_PASS` (not `DB_PASSWORD`).
