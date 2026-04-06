# 06 — Backfill Script (`packages/collector/backfill.py`)

## What This File Does

Your ML model needs **months of historical data** to train on — you can't wait weeks for the live collectors to accumulate enough. The backfill script walks backwards in time, fetching `/5m` and `/1h` snapshots for each timestamp, reconstructing the full price history across all items.

**When it runs:** Manually, once during initial setup. Then optionally periodic re-runs to expand the dataset further back in time.

---

## Strategy: Timestamped Endpoints Instead of `/timeseries`

The `/timeseries` endpoint is limited — it returns only ~365 entries per item regardless of timestep (roughly 30 hours of `5m` data, 15 days of `1h` data). **Not enough for robust ML training.**

**Better approach:** Use the regular `/5m` and `/1h` endpoints with the `timestamp` query parameter. These endpoints accept an optional `timestamp` parameter that returns prices for that specific 5-minute or 1-hour window **across all items**.

**Key insight:** Instead of iterating through 3,800 items for one timestamp, iterate through timestamps and get all items at once per request.

```
Old strategy (item-centric):
  for item_id in all_items:          # 3,800 requests per timestep
      GET /timeseries?id={item_id}&timestep=5m

New strategy (timestamp-centric):
  for timestamp in all_timestamps:   # ~1,000-2,000 requests per timestep
      GET /5m?timestamp={timestamp}  # Returns ALL items for that 5-min window
```

**Data coverage:** If you backfill 90 days of `5m` data:
- 90 days × 24 hours × 12 intervals per hour = ~25,920 timestamps
- 25,920 requests × 1 second delay = ~7 hours of backfill
- **Result:** 25,920 data points × 3,800 items = **~98 million price records** for training

Compare to `/timeseries` (30 hours per item × 3,800 items = only ~114,000 total records).

---

## How the `/5m` and `/1h` Endpoints Work with `timestamp`

**Request:**
```
GET https://prices.runescape.wiki/api/v1/osrs/5m?timestamp=1774880400
```

**Response:**
```json
{
  "timestamp": 1774880400,
  "data": {
    "2": {"avgHighPrice": 297, "highPriceVolume": 72389, "avgLowPrice": 292, "lowPriceVolume": 2902},
    "4": {"avgHighPrice": 100, "highPriceVolume": 1000, "avgLowPrice": 99, "lowPriceVolume": 500},
    // ... all tradeable items
  }
}
```

**Key detail:** The `timestamp` parameter represents the **start of that 5-minute window**. Timestamps are aligned to multiples of 300 (5 min) and 3600 (1 hour).
- Valid `5m` timestamps: `1774880400`, `1774880700`, `1774881000`, etc. (every 300 seconds)
- Valid `1h` timestamps: `1774880400`, `1774884000`, `1774887600`, etc. (every 3600 seconds)

If you request a misaligned timestamp, the API either returns no data or rounds to the nearest window. **Alignment matters.**

---

## Imports You Need

```python
import logging
import time                                     # Sleep between API requests
from datetime import datetime, timedelta, timezone

import requests

from packages.collector.db.connection import DatabaseConnection
```

---

## Constants

```python
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
FIVE_MIN_ENDPOINT: str = f"{BASE_URL}/5m"
ONE_HOUR_ENDPOINT: str = f"{BASE_URL}/1h"
USER_AGENT: str = "gept2.0 - your_contact_info"
REQUEST_TIMEOUT: int = 30
DELAY_BETWEEN_REQUESTS: float = 1.0             # Seconds between timestamp requests
BACKFILL_DAYS: int = 90                         # How many days back to backfill (from today)
FIVE_MIN_INTERVAL: int = 300                    # Seconds between 5-min windows
ONE_HOUR_INTERVAL: int = 3600                   # Seconds between 1-hour windows
```

**Why 1-second delay?** The Wiki asks you not to hammer the API. With 1-second delays, a 90-day backfill takes ~7 hours. You only run this once (or occasionally to expand history).

---

## Class: `BackfillService`

### Constructor: `__init__(self, db: DatabaseConnection)`

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `db` | `DatabaseConnection` | Shared database connection |

**What to create inside `__init__`:**
1. `self.db = db`
2. `self.session = requests.Session()` with User-Agent header
3. `self.logger = logging.getLogger(__name__)`

---

### Method: `get_item_ids(self) -> list[int]`

**What it does:** Queries the `items` table to get all item IDs. Items must be loaded first (run `ItemCollector` before backfill).

**Parameters:** None

**Returns:** `list[int]` — all item IDs in the database

**Implementation steps:**
1. Query: `SELECT item_id FROM items ORDER BY item_id`
2. Return list of IDs: `[row[0] for row in results]`

**Why query the DB instead of the API?** The `items` table is already populated by `ItemCollector`. Querying it is instant and doesn't waste an API call.

---

### Method: `get_earliest_timestamp(self, table: str) -> int | None`

**What it does:** Queries the database to find the oldest timestamp in a price table. Used to resume backfill from where it left off.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `table` | `str` | `"prices_5min"` or `"prices_1hr"` |

**Returns:** `int | None` — Unix timestamp of the earliest record, or `None` if table is empty

**Implementation steps:**
1. Query: `SELECT MIN(EXTRACT(EPOCH FROM time)) FROM {table}`
2. If result is `None`, return `None` (table is empty)
3. Otherwise, cast to int and return

**Why this method?** If backfill is interrupted and you run it again, you can resume from where you left off instead of re-processing the same data.

---

### Method: `calculate_timestamp_range(self, table: str, interval: int) -> list[int]`

**What it does:** Generates a list of valid timestamps to backfill. Walks backwards from "today" to `BACKFILL_DAYS` in the past, or from the earliest existing record if resuming.

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `table` | `str` | `"prices_5min"` | Determines interval and resume point |
| `interval` | `int` | `300` or `3600` | 5-min or 1-hour interval in seconds |

**Returns:** `list[int]` — Unix timestamps to fetch, in reverse chronological order (newest first, so you fill gaps from recent backwards)

**Implementation steps:**
1. Get the earliest existing timestamp: `earliest = self.get_earliest_timestamp(table)`
2. Calculate the oldest timestamp we want to reach:
   ```python
   now = datetime.now(timezone.utc)
   cutoff_time = now - timedelta(days=BACKFILL_DAYS)
   cutoff_ts = int(cutoff_time.timestamp())
   ```
3. Determine the starting point:
   ```python
   if earliest is None:
       start_ts = int(now.timestamp())  # Start from now
   else:
       start_ts = earliest - interval  # Resume: go one step earlier than existing
   ```
4. Generate timestamps walking backwards:
   ```python
   timestamps = []
   current_ts = start_ts
   while current_ts >= cutoff_ts:
       timestamps.append(current_ts)
       current_ts -= interval
   return timestamps
   ```
5. Log: `f"Generated {len(timestamps)} timestamps to backfill, covering {len(timestamps) * interval / 86400:.1f} days"`

**Why reverse order?** Fetching newest data first means you get recent prices in the DB quickly. If the process crashes, you still have the most valuable data for training (recent patterns).

---

### Method: `fetch_prices_at_timestamp(self, timestamp: int, endpoint: str) -> dict`

**What it does:** Calls `/5m` or `/1h` with the `timestamp` parameter and returns all items' prices for that window.

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `timestamp` | `int` | `1774880400` | Unix timestamp to fetch prices for |
| `endpoint` | `str` | `FIVE_MIN_ENDPOINT` | Which endpoint (`/5m` or `/1h`) |

**Returns:** `dict` — the full API response: `{"timestamp": ..., "data": {...}}`

**Implementation steps:**
1. Build params: `params = {"timestamp": timestamp}`
2. Make request with retry logic (3 retries, exponential backoff — same as price collectors)
3. Parse and return `response.json()`

**What to do on failure:** Log a warning and return an empty dict `{"data": {}}`. Don't re-raise — one missing timestamp shouldn't stop the entire backfill.

---

### Method: `parse_prices(self, api_response: dict) -> list[tuple]`

**What it does:** Converts the API response (all items for one timestamp) into database-ready tuples.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `api_response` | `dict` | Raw response from `fetch_prices_at_timestamp()` |

**Returns:** `list[tuple]` — tuples matching price table columns: `(time, item_id, avg_high, avg_low, high_vol, low_vol)`

**Implementation steps:**
1. Extract timestamp and convert: `unix_ts = api_response.get("timestamp")` → `snapshot_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)`
2. Get data dict: `data = api_response.get("data", {})`
3. For each item in data:
   ```python
   rows = []
   for item_id_str, price_data in data.items():
       row = (
           snapshot_time,
           int(item_id_str),
           price_data.get("avgHighPrice"),
           price_data.get("avgLowPrice"),
           price_data.get("highPriceVolume", 0),
           price_data.get("lowPriceVolume", 0),
       )
       rows.append(row)
   return rows
   ```

---

### Method: `save_prices(self, table: str, rows: list[tuple]) -> int`

**What it does:** Bulk inserts rows into `prices_5min` or `prices_1hr`.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `table` | `str` | `"prices_5min"` or `"prices_1hr"` |
| `rows` | `list[tuple]` | Output from `parse_prices()` |

**Returns:** `int` — rows inserted

**Implementation steps:**
1. Define columns: `columns = ["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]`
2. Call `self.db.bulk_insert(table=table, columns=columns, values=rows)`
3. Return the count

---

### Method: `run(self, table: str = "prices_5min", interval: int = 300) -> None`

**What it does:** Main entry point. Generates timestamp range and backfills all timestamps for a given table.

**Parameters:**
| Parameter | Type | Default | Why |
|-----------|------|---------|-----|
| `table` | `str` | `"prices_5min"` | Target table |
| `interval` | `int` | `300` | Interval in seconds (300 for 5m, 3600 for 1h) |

**Returns:** None

**Implementation steps:**
1. Determine endpoint: `endpoint = FIVE_MIN_ENDPOINT if table == "prices_5min" else ONE_HOUR_ENDPOINT`
2. Calculate timestamps: `timestamps = self.calculate_timestamp_range(table, interval)`
3. Log start: `f"Starting backfill for {table}, {len(timestamps)} timestamps to fetch"`
4. Loop through timestamps with progress tracking:
   ```python
   total_rows = 0
   for i, ts in enumerate(timestamps):
       api_response = self.fetch_prices_at_timestamp(ts, endpoint)
       rows = self.parse_prices(api_response)
       count = self.save_prices(table, rows)
       total_rows += count

       if (i + 1) % 100 == 0:
           hours_elapsed = (i + 1) * interval / 3600
           self.logger.info(f"Progress: {i + 1}/{len(timestamps)}, {total_rows} rows, ~{hours_elapsed:.1f}h of data")

       time.sleep(DELAY_BETWEEN_REQUESTS)
   ```
5. Log final summary with data coverage estimate

---

## Full Method Summary

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__(db)` | Store DB, create session | None |
| `get_earliest_timestamp(table)` | Get oldest record in table | `int \| None` |
| `calculate_timestamp_range(table, interval)` | Generate list of timestamps to backfill | `list[int]` |
| `fetch_prices_at_timestamp(ts, endpoint)` | GET `/5m` or `/1h` with timestamp param | `dict` (API response) |
| `parse_prices(api_response)` | Convert all items for one timestamp to tuples | `list[tuple]` |
| `save_prices(table, rows)` | Bulk insert rows into target table | row count |
| `run(table, interval)` | Full backfill pipeline for one table | None |

## Dependencies

Same as other collectors — `requests` only.

## Usage

```python
# In a script or __main__ block:
db = DatabaseConnection()

backfill = BackfillService(db)
backfill.run(table="prices_5min", interval=300)   # Backfill 5-min (90 days = ~7 hours)
backfill.run(table="prices_1hr", interval=3600)   # Backfill 1-hour (90 days = ~7 hours)
```

## Estimating Backfill Time

- **90 days of 5-min data:** ~25,920 timestamps × 1s delay = ~7.2 hours
- **90 days of 1-hour data:** ~2,160 timestamps × 1s delay = ~36 minutes
- **Both:** ~7.5 hours total (can be run in parallel if you're comfortable with 2 threads)

Each timestamp returns ~1,500-3,800 items depending on trading activity. So a full 90-day backfill yields:
- 5-min: 25,920 timestamps × 3,000 items = **~78 million records**
- 1-hour: 2,160 timestamps × 3,000 items = **~6.5 million records**
- **Total:** ~85 million price records — excellent training data for your ML model
