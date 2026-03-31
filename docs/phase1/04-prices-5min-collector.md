# 04 — 5-Minute Price Collector (`packages/collector/collectors/prices_5min.py`)

## What This File Does

The heartbeat of your data pipeline. Every 5 minutes, it polls the Wiki `/5m` endpoint, gets average prices and volumes for every traded item, and bulk-inserts them into `prices_5min`. This is the primary data source for your ML model.

**When it runs:** Every 300 seconds, continuously.

---

## Imports You Need

```python
import logging                                  # Log collection events
import time                                     # Track timing, calculate sleep
from datetime import datetime, timezone         # Convert Unix timestamps to Python datetimes

import requests                                 # HTTP calls to the API

from packages.collector.db.connection import DatabaseConnection
```

---

## Constants

```python
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
FIVE_MIN_ENDPOINT: str = f"{BASE_URL}/5m"
USER_AGENT: str = "gept2.0 - your_contact_info"
REQUEST_TIMEOUT: int = 30                       # Seconds before we give up on a request
COLLECTION_INTERVAL: int = 300                  # Seconds between collections (5 min)
MAX_RETRIES: int = 3                            # How many times to retry a failed request
INITIAL_BACKOFF: float = 5.0                    # Seconds to wait before first retry
```

---

## Class: `PriceCollector5Min`

### Constructor: `__init__(self, db: DatabaseConnection)`

**What it does:** Stores the DB connection, creates an HTTP session, and initializes the circuit breaker state.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `db` | `DatabaseConnection` | Shared database connection |

**What to create inside `__init__`:**
1. `self.db = db`
2. `self.session = requests.Session()`
3. `self.session.headers.update({"User-Agent": USER_AGENT})`
4. `self.logger = logging.getLogger(__name__)`
5. Circuit breaker state:
   - `self.consecutive_failures: int = 0`
   - `self.last_success_time: datetime | None = None`

**What is a circuit breaker?** If the API goes down, you don't want to hammer it with requests every 5 seconds. A circuit breaker tracks consecutive failures and adds increasing delays:
- 1st failure: wait 5s and retry
- 2nd failure: wait 10s and retry
- 3rd failure: wait 20s and retry
- After max retries: skip this cycle, try again next interval

This is called **exponential backoff** — each retry waits twice as long as the last.

---

### Method: `fetch_prices(self, timestamp: int | None = None) -> dict`

**What it does:** Calls the `/5m` endpoint and returns the parsed JSON response.

**Parameters:**
| Parameter | Type | Default | Why |
|-----------|------|---------|-----|
| `timestamp` | `int \| None` | `None` | Optional Unix timestamp to get prices for a specific 5-min window. If `None`, gets the latest. Used by the backfill script. |

**Returns:** `dict` — the full API response: `{"timestamp": 1774990800, "data": {"2": {...}, "4151": {...}, ...}}`

**Implementation steps:**
1. Build params dict: `params = {}` — if `timestamp` is provided, add `{"timestamp": timestamp}`
2. Attempt the request with retry logic:
   ```
   for attempt in range(MAX_RETRIES):
       try:
           response = self.session.get(FIVE_MIN_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
           response.raise_for_status()
           self.consecutive_failures = 0
           return response.json()
       except requests.RequestException as e:
           wait_time = INITIAL_BACKOFF * (2 ** attempt)   # 5, 10, 20 seconds
           self.logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}. Retrying in {wait_time}s")
           time.sleep(wait_time)
   ```
3. If all retries fail:
   - Increment `self.consecutive_failures`
   - Raise the exception (let `run()` handle it)

**Why retry with backoff?** The Wiki API has occasional blips. A single network timeout shouldn't lose an entire 5-minute window of data. Three retries with increasing waits handles most transient failures.

---

### Method: `parse_prices(self, api_response: dict) -> tuple[datetime, list[tuple]]`

**What it does:** Converts the raw API JSON into a timestamp and a list of database-ready tuples.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `api_response` | `dict` | The raw response from `fetch_prices()` |

**Returns:** `tuple[datetime, list[tuple]]`
- First element: the `datetime` of this price snapshot
- Second element: list of tuples, one per item, matching `prices_5min` columns

**Implementation steps:**
1. Extract the timestamp and convert to datetime:
   ```python
   unix_ts = api_response["timestamp"]
   snapshot_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
   ```
2. Get the data dict: `data = api_response.get("data", {})`
3. Build the rows list:
   ```python
   rows = []
   for item_id_str, price_data in data.items():
       item_id = int(item_id_str)  # API gives string keys, DB wants integers
       row = (
           snapshot_time,
           item_id,
           price_data.get("avgHighPrice"),     # Can be None
           price_data.get("avgLowPrice"),      # Can be None
           price_data.get("highPriceVolume", 0),
           price_data.get("lowPriceVolume", 0),
       )
       rows.append(row)
   ```
4. Log: `self.logger.info(f"Parsed {len(rows)} items for timestamp {snapshot_time}")`
5. Return `(snapshot_time, rows)`

**Key detail — None values:** Some items have `null` for `avgHighPrice` or `avgLowPrice` when no trades happened in that window. Your database columns allow NULL, so just pass `None` through. Don't skip these rows — the absence of trades is itself useful data for the ML model.

---

### Method: `save_prices(self, rows: list[tuple]) -> int`

**What it does:** Bulk inserts the parsed price rows into `prices_5min`.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `rows` | `list[tuple]` | Output from `parse_prices()` |

**Returns:** `int` — rows inserted

**Implementation steps:**
1. Define columns:
   ```python
   columns = ["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]
   ```
2. Call `self.db.bulk_insert(table="prices_5min", columns=columns, values=rows)`
3. Log and return the count

**Why `bulk_insert` and not `upsert`?** The `prices_5min` table has no primary key (TimescaleDB hypertable). Each 5-minute snapshot is a new set of rows. If you run the collector twice for the same timestamp, you'd get duplicates. To prevent this, check for duplicates in `run()` before inserting (see below).

---

### Method: `is_duplicate(self, snapshot_time: datetime) -> bool`

**What it does:** Checks if we already have data for this timestamp. Prevents duplicate inserts if the collector runs twice in the same window.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `snapshot_time` | `datetime` | The timestamp from the API response |

**Returns:** `bool` — `True` if data already exists for this timestamp

**Implementation steps:**
1. Query the database:
   ```python
   result = self.db.execute_query(
       "SELECT 1 FROM prices_5min WHERE time = %s LIMIT 1",
       (snapshot_time,)
   )
   ```
2. Return `len(result) > 0`

**Why check?** If the scheduler fires slightly early or the API returns cached data, you might get the same timestamp twice. This check is cheap (indexed query) and prevents bloating your table with duplicate rows.

---

### Method: `run(self) -> None`

**What it does:** The main entry point. Orchestrates one collection cycle: fetch → check duplicate → parse → save → update status.

**Parameters:** None

**Returns:** None

**Implementation steps:**
1. Log start
2. `api_response = self.fetch_prices()`
3. `snapshot_time, rows = self.parse_prices(api_response)`
4. Check for duplicates:
   ```python
   if self.is_duplicate(snapshot_time):
       self.logger.info(f"Data for {snapshot_time} already exists, skipping")
       return
   ```
5. `count = self.save_prices(rows)`
6. Update `self.last_success_time = datetime.now(timezone.utc)`
7. Update `collection_status` table (same pattern as items collector)
8. Wrap in `try/except`:
   - On failure: log error, update `collection_status` with failure info
   - Don't re-raise (scheduler keeps running)

---

### Method: `run_loop(self) -> None`

**What it does:** Runs the collector in a continuous loop, sleeping between collections. This is what your Docker container's entrypoint calls.

**Parameters:** None

**Returns:** Never returns (runs forever)

**Implementation steps:**
1. Log: `"Starting 5-minute price collector loop"`
2. Infinite loop:
   ```python
   while True:
       start_time = time.time()
       self.run()                          # Do one collection
       elapsed = time.time() - start_time
       sleep_time = max(0, COLLECTION_INTERVAL - elapsed)   # Account for collection time
       self.logger.debug(f"Sleeping {sleep_time:.0f}s until next collection")
       time.sleep(sleep_time)
   ```

**Why subtract elapsed time?** If the collection itself takes 15 seconds, you want to sleep 285 seconds, not 300. This keeps your collection aligned to roughly every 5 minutes.

---

## Full Method Summary

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__(db)` | Store DB, create session, init circuit breaker | None |
| `fetch_prices(timestamp?)` | GET `/5m`, retry with backoff | `dict` (API response) |
| `parse_prices(api_response)` | Convert JSON to DB-ready tuples | `(datetime, list[tuple])` |
| `save_prices(rows)` | Bulk insert into `prices_5min` | row count |
| `is_duplicate(snapshot_time)` | Check if timestamp already collected | `bool` |
| `run()` | One collection cycle | None |
| `run_loop()` | Infinite collection loop | Never returns |

## Dependencies

```toml
requests = "^2.31"
```
