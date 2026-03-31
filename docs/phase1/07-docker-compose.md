# 07 — Docker Compose & Project Config

## What This File Does

`docker-compose.yml` defines every service your project needs and how they talk to each other. One command (`docker compose up`) starts everything — database, collectors, and later the API and frontend.

---

## File: `docker-compose.yml`

This is not Python — it's YAML (a config format). Indentation matters (use 2 spaces, not tabs).

### Services to Define

```yaml
services:
  db:
    # The database
  collector:
    # The price + item data collectors
```

---

### Service: `db` (TimescaleDB)

**What it does:** Runs PostgreSQL with the TimescaleDB extension pre-installed.

**Configuration you need:**

| Field | Value | Why |
|-------|-------|-----|
| `image` | `timescale/timescaledb:latest-pg16` | Official TimescaleDB image with PostgreSQL 16. Gets you TimescaleDB without manual installation. |
| `container_name` | `gept-db` | A readable name so you can reference it easily in logs/commands. |
| `ports` | `"5432:5432"` | Maps port 5432 inside the container to 5432 on your machine. This lets you connect to the DB from your host (e.g., with pgAdmin or DBeaver for inspection). |
| `environment` | see below | Database credentials |
| `volumes` | see below | Persist data + load schema |
| `restart` | `unless-stopped` | Auto-restart if the container crashes. Only stops if YOU manually stop it. |
| `healthcheck` | see below | Docker checks if the DB is actually ready before starting dependent services |

**Environment variables:**
```yaml
environment:
  POSTGRES_DB: ${DB_NAME}           # Reads from .env file
  POSTGRES_USER: ${DB_USER}
  POSTGRES_PASSWORD: ${DB_PASSWORD}
```

**Volumes:**
```yaml
volumes:
  - pgdata:/var/lib/postgresql/data                             # Persist data between restarts
  - ./packages/collector/db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql  # Auto-run schema on first start
```

- **`pgdata:/var/lib/postgresql/data`** — A named volume. Without this, all your data disappears when the container restarts. The volume stores the actual database files on your machine's disk.
- **`schema.sql` mount** — PostgreSQL automatically runs any `.sql` files in `/docker-entrypoint-initdb.d/` when the container starts for the first time (empty database). Your schema creates the tables automatically. The `01-` prefix controls execution order if you add more files later.

**Healthcheck:**
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
  interval: 10s
  timeout: 5s
  retries: 5
```

**What is a healthcheck?** Docker periodically runs this command inside the container. `pg_isready` checks if PostgreSQL is accepting connections. Until this passes, Docker considers the service "unhealthy" and won't start services that depend on it. Without this, your collector might start before the database is ready and crash.

---

### Service: `collector`

**What it does:** Runs your Python collector code.

**Configuration you need:**

| Field | Value | Why |
|-------|-------|-----|
| `build` | `context: .` with `dockerfile: packages/collector/Dockerfile` | Builds a Docker image from your collector code |
| `container_name` | `gept-collector` | Readable name |
| `depends_on` | `db: condition: service_healthy` | Wait for the DB healthcheck to pass before starting |
| `environment` | DB credentials + API config | Same DB vars as the `db` service, plus your User-Agent |
| `restart` | `unless-stopped` | Auto-restart on crash |

**Environment:**
```yaml
environment:
  DB_HOST: db                        # "db" = the service name above. Docker networking resolves this.
  DB_PORT: "5432"
  DB_NAME: ${DB_NAME}
  DB_USER: ${DB_USER}
  DB_PASSWORD: ${DB_PASSWORD}
  USER_AGENT: ${USER_AGENT}
```

**Why `DB_HOST: db`?** Docker Compose creates a private network for your services. Each service can reach others by their service name. So `db` resolves to the database container's IP address. Your Python code reads `os.getenv("DB_HOST")` and gets `"db"`, which psycopg2 resolves through Docker's internal DNS.

**`depends_on` with condition:**
```yaml
depends_on:
  db:
    condition: service_healthy
```

This means: "Don't start the collector until the `db` service's healthcheck passes." Without `condition: service_healthy`, Docker only waits for the container to START (not for PostgreSQL to actually be ready).

---

### Named Volumes

At the bottom of the file, declare the named volume:

```yaml
volumes:
  pgdata:
```

This tells Docker to create a persistent volume called `pgdata` that survives container restarts and rebuilds.

---

## File: `.env`

Lives in the project root. Docker Compose reads this automatically. **Add to `.gitignore`.**

```env
# Database
DB_NAME=gept
DB_USER=gept
DB_PASSWORD=your_secure_password_here

# API
USER_AGENT=gept2.0 - your_contact_info
```

---

## File: `packages/collector/Dockerfile`

Builds the collector into a Docker image.

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY pyproject.toml poetry.lock* ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --no-dev

# Copy source code
COPY packages/collector ./packages/collector

# Run the collector entry point
CMD ["python", "-m", "packages.collector.main"]
```

**Line-by-line explanation:**

| Line | What It Does |
|------|-------------|
| `FROM python:3.12-slim` | Base image: Python 3.12, "slim" variant (smaller download, no unnecessary tools) |
| `WORKDIR /app` | Set the working directory inside the container |
| `RUN apt-get ... libpq-dev gcc` | Install system libraries that `psycopg2` needs to compile. `libpq-dev` is the PostgreSQL client library. |
| `COPY pyproject.toml ...` | Copy dependency files first (Docker caches this layer — if deps don't change, it doesn't reinstall) |
| `RUN pip install poetry ...` | Install Poetry, then install your project's dependencies |
| `COPY packages/collector ...` | Copy your actual code (done last so code changes don't bust the dependency cache) |
| `CMD [...]` | The command that runs when the container starts |

---

## File: `packages/collector/main.py`

The entry point that starts all collectors. This is what the Dockerfile's `CMD` runs.

### Imports

```python
import logging
import threading

from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector
from packages.collector.collectors.prices_5min import PriceCollector5Min
from packages.collector.collectors.prices_1hr import PriceCollector1Hr
```

### What `main()` Should Do

1. **Configure logging:**
   ```python
   logging.basicConfig(
       level=logging.INFO,
       format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
   )
   ```

2. **Create the shared database connection:**
   ```python
   db = DatabaseConnection()
   ```

3. **Run item collection first** (other collectors need item data):
   ```python
   items = ItemCollector(db)
   items.run()
   ```

4. **Start each price collector in its own thread:**
   ```python
   collector_5min = PriceCollector5Min(db)
   collector_1hr = PriceCollector1Hr(db)

   thread_5min = threading.Thread(target=collector_5min.run_loop, daemon=True)
   thread_1hr = threading.Thread(target=collector_1hr.run_loop, daemon=True)

   thread_5min.start()
   thread_1hr.start()
   ```

5. **Keep the main thread alive** (daemon threads die if main exits):
   ```python
   thread_5min.join()
   thread_1hr.join()
   ```

**Why threads?** The 5-min and 1-hr collectors run on different schedules. Threads let them sleep independently without blocking each other. `daemon=True` means they'll stop automatically if the main thread crashes (clean shutdown).

---

## File: `pyproject.toml`

Poetry's project configuration. Defines your Python dependencies.

```toml
[tool.poetry]
name = "gept2"
version = "0.1.0"
description = "OSRS Grand Exchange flipping tool with AI price prediction"
authors = ["Your Name"]

[tool.poetry.dependencies]
python = "^3.12"
psycopg2-binary = "^2.9"     # PostgreSQL driver
requests = "^2.31"            # HTTP client for Wiki API

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

---

## File: `.gitignore`

```
.env
__pycache__/
*.pyc
.venv/
pgdata/
```

Never commit `.env` (contains passwords) or `__pycache__` (compiled Python files).

---

## Startup Flow

```
docker compose up
    │
    ├── 1. Start "db" service (TimescaleDB)
    │       └── Runs schema.sql on first boot (creates tables)
    │       └── Healthcheck: pg_isready loops until DB accepts connections
    │
    └── 2. Start "collector" service (waits for db healthy)
            └── main.py runs:
                ├── ItemCollector.run() — loads item metadata
                ├── PriceCollector5Min.run_loop() — starts in thread, polls every 5 min
                └── PriceCollector1Hr.run_loop() — starts in thread, polls every 1 hour
```
