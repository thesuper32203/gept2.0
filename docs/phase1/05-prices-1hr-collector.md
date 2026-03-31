# 05 — 1-Hour Price Collector (`packages/collector/collectors/prices_1hr.py`)

## What This File Does

Same pattern as the 5-min collector, but polls the `/1h` endpoint every 3600 seconds. This captures longer-term trends used by the ML model's long encoder (14-day lookback for overnight flip predictions).

**When it runs:** Every 3600 seconds (1 hour), continuously.

---

## Imports You Need

```python
import logging
import time
from datetime import datetime, timezone

import requests

from packages.collector.db.connection import DatabaseConnection
```

Identical to the 5-min collector. Same libraries, same reasons.

---

## Constants

```python
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
ONE_HOUR_ENDPOINT: str = f"{BASE_URL}/1h"
USER_AGENT: str = "gept2.0 - your_contact_info"
REQUEST_TIMEOUT: int = 30
COLLECTION_INTERVAL: int = 3600                  # 1 hour
MAX_RETRIES: int = 3
INITIAL_BACKOFF: float = 10.0                    # Slightly longer initial backoff — less urgency
```

---

## Class: `PriceCollector1Hr`

### This Class Is Nearly Identical to `PriceCollector5Min`

The structure, methods, and logic are the same. The only differences are:

| Difference | 5-Min Collector | 1-Hr Collector |
|-----------|-----------------|----------------|
| Endpoint | `/5m` | `/1h` |
| Target table | `prices_5min` | `prices_1hr` |
| Poll interval | 300s | 3600s |
| Initial backoff | 5s | 10s |
| Collector name in status table | `"collector_5min"` | `"collector_1hr"` |

### Should You Duplicate the Code?

**No.** This is a great opportunity to practice the DRY principle (Don't Repeat Yourself). You have two options:

#### Option A: Base Class (Recommended)

Create a base class that both collectors inherit from:

```
packages/collector/collectors/
├── base.py          # BasePriceCollector — shared logic
├── prices_5min.py   # PriceCollector5Min(BasePriceCollector)
├── prices_1hr.py    # PriceCollector1Hr(BasePriceCollector)
└── items.py         # ItemCollector (different enough to stay separate)
```

**`base.py`** would contain a class `BasePriceCollector` with:
- All the shared methods: `fetch_prices`, `parse_prices`, `save_prices`, `is_duplicate`, `run`, `run_loop`
- Constructor takes config parameters instead of hardcoding them

**Then each subclass just sets its config:**

```python
# In prices_5min.py — this is ALL you'd write
class PriceCollector5Min(BasePriceCollector):
    def __init__(self, db: DatabaseConnection) -> None:
        super().__init__(
            db=db,
            endpoint=f"{BASE_URL}/5m",
            table="prices_5min",
            interval=300,
            collector_name="collector_5min",
        )
```

```python
# In prices_1hr.py — same pattern
class PriceCollector1Hr(BasePriceCollector):
    def __init__(self, db: DatabaseConnection) -> None:
        super().__init__(
            db=db,
            endpoint=f"{BASE_URL}/1h",
            table="prices_1hr",
            interval=3600,
            collector_name="collector_1hr",
        )
```

#### Option B: Copy and Change Constants

If you're not comfortable with inheritance yet, copy the 5-min collector and change the 5 constants listed in the table above. It works fine — you can refactor to Option A later when you're ready.

---

## Base Class Blueprint (`packages/collector/collectors/base.py`)

If you go with Option A, here's the base class:

### Imports

```python
import logging
import time
from datetime import datetime, timezone

import requests

from packages.collector.db.connection import DatabaseConnection
```

### Constructor: `__init__(self, db, endpoint, table, interval, collector_name, max_retries=3, initial_backoff=5.0)`

**Parameters:**
| Parameter | Type | Default | Why |
|-----------|------|---------|-----|
| `db` | `DatabaseConnection` | required | Shared database connection |
| `endpoint` | `str` | required | Full API URL (e.g., `"https://prices.runescape.wiki/api/v1/osrs/5m"`) |
| `table` | `str` | required | Target table name (e.g., `"prices_5min"`) |
| `interval` | `int` | required | Seconds between collections |
| `collector_name` | `str` | required | Name for the `collection_status` table |
| `max_retries` | `int` | `3` | Retry attempts on failure |
| `initial_backoff` | `float` | `5.0` | Seconds before first retry |

**All the methods from `04-prices-5min-collector.md` go here**, but using `self.endpoint`, `self.table`, `self.interval`, `self.collector_name` instead of hardcoded constants.

---

## Full Method Summary (Same as 5-Min)

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__(db, endpoint, table, interval, collector_name)` | Store config, create session | None |
| `fetch_prices(timestamp?)` | GET endpoint, retry with backoff | `dict` |
| `parse_prices(api_response)` | Convert JSON to tuples | `(datetime, list[tuple])` |
| `save_prices(rows)` | Bulk insert into target table | row count |
| `is_duplicate(snapshot_time)` | Check for existing data | `bool` |
| `run()` | One collection cycle | None |
| `run_loop()` | Infinite collection loop | Never returns |

## Dependencies

Same as 5-min collector — no new dependencies.
