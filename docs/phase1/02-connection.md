# 02 — Database Connection (`packages/collector/db/connection.py`)

## What This File Does

Provides a single reusable class that all your collectors use to talk to PostgreSQL. Instead of every file opening its own database connection with raw credentials, they all call `DatabaseConnection` — one place to manage the connection string, connection pooling, and error handling.

---

## Imports You Need

```python
import os                           # Read database credentials from environment variables
import logging                      # Log connection events and errors
from contextlib import contextmanager  # Create a clean "with db.get_cursor() as cur:" pattern

import psycopg2                     # PostgreSQL driver — the library that talks to your database
import psycopg2.pool                # Connection pooling — reuse connections instead of opening new ones
import psycopg2.extras              # Extra cursor types (execute_values for bulk inserts)
```

### Why These Libraries?

- **`psycopg2`** — The most mature Python PostgreSQL driver. Battle-tested, fast, widely documented. Install with `psycopg2-binary` in development (pre-compiled) or `psycopg2` in production (compiled from source for performance).
- **`psycopg2.pool`** — Opening a database connection takes ~50-100ms. If your collector opens a new connection every 5 minutes, that's fine. But if you're doing bulk inserts (backfill), opening a connection per insert would be brutally slow. A **connection pool** keeps a set of connections open and hands them out on demand.
- **`psycopg2.extras.execute_values`** — Lets you insert thousands of rows in a single query instead of one-at-a-time. Critical for performance during backfill and batch price inserts.

---

## Class: `DatabaseConnection`

### Constructor: `__init__(self)`

**What it does:** Reads database credentials from environment variables and creates a connection pool.

**Environment variables to read:**
| Variable | Example Value | What It Is |
|----------|--------------|------------|
| `DB_HOST` | `db` | Hostname of the database. In Docker, this is the service name from `docker-compose.yml`. |
| `DB_PORT` | `5432` | PostgreSQL default port. |
| `DB_NAME` | `gept` | Name of the database. |
| `DB_USER` | `gept` | Database username. |
| `DB_PASSWORD` | `your_password_here` | Database password. Stored in `.env` file, never in code. |

**What to create inside `__init__`:**
1. Read each env var using `os.getenv("DB_HOST", "localhost")` — the second argument is a default fallback for local development
2. Create a `psycopg2.pool.ThreadedConnectionPool` with:
   - `minconn=1` — keep at least 1 connection alive
   - `maxconn=5` — allow up to 5 simultaneous connections
   - Pass the connection string using the env vars
3. Set up a `logging.getLogger(__name__)` for this class

**Why a pool?** Even though your collectors are simple, the backfill script might run multiple item backfills concurrently. A pool prevents "too many connections" errors and reuses existing connections efficiently.

**Why environment variables?** Never hardcode passwords. The `.env` file stays on your machine (add it to `.gitignore`), and Docker Compose automatically loads it into each container's environment.

```python
def __init__(self) -> None:
    # Read config from environment
    # Create ThreadedConnectionPool
    # Set up logger
```

---

### Method: `get_cursor(self)`

**What it does:** A context manager that checks out a connection from the pool, creates a cursor, yields it for your code to use, commits the transaction when done, and returns the connection to the pool. If anything goes wrong, it rolls back.

**Decorator:** `@contextmanager` (from `contextlib`)

**Parameters:** None

**Returns/Yields:** A `psycopg2.cursor` object

**How you'll use it:**
```python
db = DatabaseConnection()
with db.get_cursor() as cursor:
    cursor.execute("SELECT * FROM items WHERE item_id = %s", (4151,))
    row = cursor.fetchone()
```

**Implementation steps:**
1. Get a connection from `self.pool.getconn()`
2. Create a cursor from that connection: `conn.cursor()`
3. `yield cursor` — control passes to the caller's `with` block
4. If no exception: `conn.commit()` — save changes to the database
5. If exception: `conn.rollback()` — undo any partial changes, then log the error and re-raise
6. In the `finally` block (always runs): close the cursor and return the connection to the pool with `self.pool.putconn(conn)`

**Why a context manager?** Without it, you'd have to remember to commit, rollback, close the cursor, and return the connection EVERY time. One missed `putconn()` and your pool runs dry. The context manager makes this impossible to mess up.

---

### Method: `bulk_insert(self, table: str, columns: list[str], values: list[tuple]) -> int`

**What it does:** Inserts many rows at once using `psycopg2.extras.execute_values`. Returns the number of rows inserted.

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `table` | `str` | `"prices_5min"` | Which table to insert into |
| `columns` | `list[str]` | `["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]` | Column names for the INSERT |
| `values` | `list[tuple]` | `[(datetime, 4151, 1252484, 1228665, 4, 6), ...]` | List of row tuples to insert |

**Returns:** `int` — number of rows inserted

**Implementation steps:**
1. Use `get_cursor()` context manager
2. Build the SQL template: `INSERT INTO {table} ({columns}) VALUES %s`
   - **IMPORTANT**: Use `sql.SQL` and `sql.Identifier` from `psycopg2.sql` to safely build the table/column names (prevents SQL injection). Only the VALUES placeholder uses `%s`.
3. Call `psycopg2.extras.execute_values(cursor, sql_template, values, page_size=1000)`
   - `page_size=1000` means it sends 1000 rows per batch to the database. More efficient than one-at-a-time but doesn't overload memory.
4. Return `cursor.rowcount`

**Why `execute_values`?** Inserting 3,000 items one at a time = 3,000 round trips to the database. `execute_values` batches them into ~3 round trips. The `/5m` endpoint returns data for all traded items (potentially 3,000+), so this matters.

---

### Method: `upsert(self, table: str, columns: list[str], values: list[tuple], conflict_columns: list[str]) -> int`

**What it does:** Inserts rows, but if a row with the same key already exists, it updates it instead of failing. This is called an "upsert" (INSERT ... ON CONFLICT ... DO UPDATE).

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `table` | `str` | `"items"` | Target table |
| `columns` | `list[str]` | `["item_id", "name", "members", ...]` | All columns |
| `values` | `list[tuple]` | `[(4151, "Abyssal whip", True, ...)]` | Row data |
| `conflict_columns` | `list[str]` | `["item_id"]` | Which columns define uniqueness (usually the primary key) |

**Returns:** `int` — number of rows affected

**Implementation steps:**
1. Use `get_cursor()`
2. Build SQL:
   ```sql
   INSERT INTO {table} ({columns})
   VALUES %s
   ON CONFLICT ({conflict_columns})
   DO UPDATE SET col1 = EXCLUDED.col1, col2 = EXCLUDED.col2, ...
   ```
   - `EXCLUDED` refers to the row that was rejected — it lets you say "use the new values"
   - Generate the `SET` clause for all non-conflict columns
3. Execute with `execute_values`
4. Return `cursor.rowcount`

**When you'll use this:** The `items` table has a `PRIMARY KEY` on `item_id`. When you refresh item metadata daily, some items already exist. Without upsert, the insert would fail with a duplicate key error.

---

### Method: `execute_query(self, query: str, params: tuple | None = None) -> list[tuple]`

**What it does:** Runs a SELECT query and returns all results. For read operations.

**Parameters:**
| Parameter | Type | Example |
|-----------|------|---------|
| `query` | `str` | `"SELECT * FROM prices_5min WHERE item_id = %s AND time > %s"` |
| `params` | `tuple \| None` | `(4151, some_datetime)` |

**Returns:** `list[tuple]` — all rows from the query result

**Implementation steps:**
1. Use `get_cursor()`
2. `cursor.execute(query, params)`
3. Return `cursor.fetchall()`

**IMPORTANT — SQL injection prevention:** ALWAYS use parameterized queries (`%s` placeholders + params tuple). Never use f-strings or string concatenation to build queries with user data.

---

### Method: `close(self) -> None`

**What it does:** Closes all connections in the pool. Call this when shutting down.

**Implementation:** `self.pool.closeall()`

---

## Full Method Summary

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__()` | Create connection pool from env vars | None |
| `get_cursor()` | Context manager — checkout/commit/return connection | yields `cursor` |
| `bulk_insert(table, columns, values)` | Fast multi-row INSERT | row count |
| `upsert(table, columns, values, conflict_columns)` | INSERT or UPDATE existing rows | row count |
| `execute_query(query, params)` | Run a SELECT, return results | list of tuples |
| `close()` | Shut down the pool | None |

## Dependencies to Add to `pyproject.toml`

```toml
[tool.poetry.dependencies]
psycopg2-binary = "^2.9"   # PostgreSQL driver (use psycopg2-binary for easy install)
```
