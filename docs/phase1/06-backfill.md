# 06 — Backfill Script (`packages/collector/backfill.py`)

## What This File Does

Your ML model needs historical data to train on — you can't wait weeks for the collectors to accumulate enough. The backfill script pulls historical price data for each item using the Wiki's `/timeseries` endpoint and loads it into your database.

**When it runs:** Manually, once during initial setup, and optionally again if you lose data or want to refresh.

---

## Important Limitation

The `/timeseries` endpoint returns data for **one item at a time**. With ~3,800 tradeable items, that's ~3,800 API requests. You need to:
1. Be respectful — don't flood the API. Add a delay between requests.
2. Be smart — prioritize high-volume items first (they're more useful for the ML model).
3. Be resilient — if you get interrupted halfway, pick up where you left off.

---

## Imports You Need

```python
import logging
import time                                     # Sleep between API requests
from datetime import datetime, timezone

import requests

from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector  # To get the item list
```

---

## Constants

```python
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
TIMESERIES_ENDPOINT: str = f"{BASE_URL}/timeseries"
USER_AGENT: str = "gept2.0 - your_contact_info"
REQUEST_TIMEOUT: int = 30
DELAY_BETWEEN_REQUESTS: float = 1.0             # Seconds between items — be respectful
TIMESTEPS: list[str] = ["5m", "1h"]             # Fetch both resolutions
```

**Why 1-second delay?** The Wiki asks you not to hammer the API. 3,800 items × 1 second = ~63 minutes for a full backfill per timestep. That's long but respectful. You only run this once.

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

### Method: `get_already_backfilled(self, table: str) -> set[int]`

**What it does:** Checks which items already have data in a given table. Used to skip items on re-runs (resume capability).

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `table` | `str` | `"prices_5min"` or `"prices_1hr"` |

**Returns:** `set[int]` — item IDs that already have data

**Implementation steps:**
1. Query: `SELECT DISTINCT item_id FROM {table}`
2. Return as a set: `{row[0] for row in results}`

**Why a set?** Checking `if item_id in already_done` is O(1) with a set vs O(n) with a list. With 3,800 items, this matters.

---

### Method: `fetch_timeseries(self, item_id: int, timestep: str) -> list[dict]`

**What it does:** Calls the `/timeseries` endpoint for a single item and returns the data entries.

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `item_id` | `int` | `4151` | Which item to fetch history for |
| `timestep` | `str` | `"5m"` or `"1h"` | Resolution of the data |

**Returns:** `list[dict]` — list of price data entries

**Implementation steps:**
1. Build params: `{"id": item_id, "timestep": timestep}`
2. Make request with retry logic (same pattern as the price collectors — 3 retries, exponential backoff)
3. Parse response: `data = response.json()`
4. Return `data.get("data", [])`

**What the response looks like:**
```python
# /timeseries?id=4151&timestep=5m returns:
{
    "itemId": 4151,
    "data": [
        {
            "timestamp": 1774880400,
            "avgHighPrice": 1252484,
            "avgLowPrice": 1228665,
            "highPriceVolume": 4,
            "lowPriceVolume": 6
        },
        # ... ~365 more entries for 5m (~30 hours of history)
        # ... ~365 more entries for 1h (~15 days of history)
    ]
}
```

**Note on data volume:** The `/timeseries` endpoint returns a limited window — roughly 365 entries regardless of timestep. For `5m` that's ~30 hours. For `1h` that's ~15 days. This is enough to start training but you'll accumulate more as your live collectors run.

---

### Method: `parse_timeseries(self, item_id: int, entries: list[dict]) -> list[tuple]`

**What it does:** Converts timeseries entries into database-ready tuples. Same logic as `PriceCollector5Min.parse_prices` but for a single item.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `item_id` | `int` | The item these entries belong to |
| `entries` | `list[dict]` | Raw entries from `fetch_timeseries()` |

**Returns:** `list[tuple]` — tuples matching price table columns

**Implementation steps:**
1. For each entry:
   ```python
   row = (
       datetime.fromtimestamp(entry["timestamp"], tz=timezone.utc),
       item_id,
       entry.get("avgHighPrice"),      # Can be None
       entry.get("avgLowPrice"),       # Can be None
       entry.get("highPriceVolume", 0),
       entry.get("lowPriceVolume", 0),
   )
   ```
2. Return the list of tuples

---

### Method: `backfill_item(self, item_id: int, timestep: str, table: str) -> int`

**What it does:** Full backfill pipeline for one item + one timestep. Fetch → parse → save.

**Parameters:**
| Parameter | Type | Example | Why |
|-----------|------|---------|-----|
| `item_id` | `int` | `4151` | Item to backfill |
| `timestep` | `str` | `"5m"` | API timestep parameter |
| `table` | `str` | `"prices_5min"` | Target table |

**Returns:** `int` — rows inserted

**Implementation steps:**
1. `entries = self.fetch_timeseries(item_id, timestep)`
2. If no entries: log and return 0
3. `rows = self.parse_timeseries(item_id, entries)`
4. `count = self.db.bulk_insert(table=table, columns=[...], values=rows)`
5. Return count

---

### Method: `run(self, timestep: str = "5m", priority_items: list[int] | None = None) -> None`

**What it does:** Main entry point. Backfills all items (or a priority subset) for a given timestep.

**Parameters:**
| Parameter | Type | Default | Why |
|-----------|------|---------|-----|
| `timestep` | `str` | `"5m"` | Which resolution to backfill |
| `priority_items` | `list[int] \| None` | `None` | If provided, only backfill these items. Useful for testing or prioritizing high-volume items. |

**Returns:** None

**Implementation steps:**
1. Determine target table: `"prices_5min"` if timestep is `"5m"`, `"prices_1hr"` if `"1h"`
2. Get all item IDs: `all_items = self.get_item_ids()`
3. Get already-done items: `done = self.get_already_backfilled(table)`
4. Filter to remaining items:
   ```python
   if priority_items:
       items_to_do = [i for i in priority_items if i not in done]
   else:
       items_to_do = [i for i in all_items if i not in done]
   ```
5. Log: `f"Backfilling {len(items_to_do)} items ({len(done)} already done)"`
6. Loop with progress tracking:
   ```python
   total_rows = 0
   for i, item_id in enumerate(items_to_do):
       try:
           count = self.backfill_item(item_id, timestep, table)
           total_rows += count
           if (i + 1) % 100 == 0:  # Progress log every 100 items
               self.logger.info(f"Progress: {i + 1}/{len(items_to_do)} items, {total_rows} total rows")
       except Exception as e:
           self.logger.error(f"Failed to backfill item {item_id}: {e}")
           # Don't stop — continue with next item
       time.sleep(DELAY_BETWEEN_REQUESTS)
   ```
7. Log final summary: total items processed, total rows inserted, time elapsed

---

## Full Method Summary

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__(db)` | Store DB, create session | None |
| `get_item_ids()` | Get all item IDs from DB | `list[int]` |
| `get_already_backfilled(table)` | Check which items have data | `set[int]` |
| `fetch_timeseries(item_id, timestep)` | GET `/timeseries` for one item | `list[dict]` |
| `parse_timeseries(item_id, entries)` | Convert entries to tuples | `list[tuple]` |
| `backfill_item(item_id, timestep, table)` | Full pipeline for one item | row count |
| `run(timestep, priority_items?)` | Backfill all/priority items | None |

## Dependencies

Same as other collectors — `requests` only.

## Usage

```python
# In a script or __main__ block:
db = DatabaseConnection()
items_collector = ItemCollector(db)
items_collector.run()                      # Load item metadata first

backfill = BackfillService(db)
backfill.run(timestep="5m")                # Backfill 5-min data (~1 hour)
backfill.run(timestep="1h")                # Backfill 1-hr data (~1 hour)
```
