# 03 — Item Metadata Collector (`packages/collector/collectors/items.py`)

## What This File Does

Fetches the master list of all OSRS items from the Wiki `/mapping` endpoint and stores them in the `items` table. This gives every item a name, buy limit, and members status that the other collectors and the future recommendation engine will reference.

**When it runs:** Once at startup, then once per day (items rarely change, but Jagex adds new ones with updates).

---

## Imports You Need

```python
import logging                      # Log what's happening (items fetched, errors, etc.)
from datetime import datetime, timezone  # Timestamp for last_updated column

import requests                     # HTTP library to call the Wiki API

from packages.collector.db.connection import DatabaseConnection  # Your DB class from step 2
```

### Why `requests`?

The simplest, most widely-used HTTP library in Python. You could use `httpx` (async-capable) or `aiohttp` — but `requests` is synchronous and easier to reason about. Since this collector runs once a day, async provides no benefit here.

---

## Constants

```python
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
MAPPING_ENDPOINT: str = f"{BASE_URL}/mapping"
USER_AGENT: str = "gept2.0 - your_contact_info"   # REQUIRED by the Wiki API
REQUEST_TIMEOUT: int = 30                           # Seconds before request fails
```

**Why constants?** No magic strings scattered through your code. If the API URL changes, you update one line. The `USER_AGENT` is required — the Wiki blocks default user agents.

---

## Class: `ItemCollector`

### Constructor: `__init__(self, db: DatabaseConnection)`

**What it does:** Stores the database connection and sets up the HTTP session with the required headers.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `db` | `DatabaseConnection` | The shared database connection from `connection.py` |

**What to create inside `__init__`:**
1. Store `self.db = db`
2. Create `self.session = requests.Session()` — a session reuses the TCP connection across requests (faster than creating a new connection each time)
3. Set the User-Agent header on the session: `self.session.headers.update({"User-Agent": USER_AGENT})`
4. Set up `self.logger = logging.getLogger(__name__)`

**Why a Session?** Even though this collector only makes one request per day, using a Session is best practice. It also makes it easy to add retry logic later without changing every request call.

---

### Method: `fetch_items(self) -> list[dict]`

**What it does:** Calls the `/mapping` endpoint and returns the raw JSON list of item dicts.

**Parameters:** None

**Returns:** `list[dict]` — each dict has keys: `id`, `name`, `members`, `limit`, `highalch`, `lowalch`, `value`, `examine`, `icon`

**Implementation steps:**
1. `response = self.session.get(MAPPING_ENDPOINT, timeout=REQUEST_TIMEOUT)`
2. `response.raise_for_status()` — raises an exception if the API returned 4xx or 5xx
3. `data = response.json()` — parse JSON response into Python list
4. Log the count: `self.logger.info(f"Fetched {len(data)} items from mapping API")`
5. Return `data`

**Error handling:** Wrap in `try/except requests.RequestException` to catch network errors, timeouts, and bad status codes. Log the error and re-raise (let the caller decide what to do).

**What the response looks like:**
```python
[
    {
        "id": 10344,
        "name": "3rd age amulet",
        "members": True,
        "limit": 8,
        "highalch": 30300,
        "lowalch": 20200,
        "value": 50500,
        "examine": "Fabulously ancient mage protection enchanted in the 3rd Age.",
        "icon": "3rd age amulet.png"
    },
    # ... ~3,800 more items
]
```

---

### Method: `parse_items(self, raw_items: list[dict]) -> list[tuple]`

**What it does:** Transforms the raw API response into a list of tuples ready for database insertion. Handles missing fields gracefully.

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `raw_items` | `list[dict]` | The raw JSON from `fetch_items()` |

**Returns:** `list[tuple]` — each tuple matches the `items` table columns: `(item_id, name, members, buy_limit, high_alch, low_alch, value, examine, icon, last_updated)`

**Implementation steps:**
1. Get current timestamp: `now = datetime.now(timezone.utc)`
2. Loop through each item dict
3. For each item, extract fields using `.get()` with defaults for missing values:
   - `item.get("id")` — skip the item if this is missing (it's required)
   - `item.get("name", "Unknown")` — default to "Unknown" if no name
   - `item.get("members", False)`
   - `item.get("limit")` — this can be `None` (some items don't have a buy limit)
   - `item.get("highalch")`, `item.get("lowalch")`, `item.get("value")`
   - `item.get("examine", "")`, `item.get("icon", "")`
4. Build tuple: `(id, name, members, limit, highalch, lowalch, value, examine, icon, now)`
5. Return the list of tuples

**Why parse separately from fetch?** Separation of concerns. `fetch_items` handles the network. `parse_items` handles data transformation. If the API changes its field names, you only change `parse_items`. If you need to test parsing logic, you can pass in fake data without hitting the API.

---

### Method: `save_items(self, parsed_items: list[tuple]) -> int`

**What it does:** Writes the parsed items to the `items` table using upsert (insert new items, update existing ones).

**Parameters:**
| Parameter | Type | Why |
|-----------|------|-----|
| `parsed_items` | `list[tuple]` | Output from `parse_items()` |

**Returns:** `int` — number of rows affected

**Implementation steps:**
1. Define the column list:
   ```python
   columns = [
       "item_id", "name", "members", "buy_limit",
       "high_alch", "low_alch", "value", "examine",
       "icon", "last_updated"
   ]
   ```
2. Call `self.db.upsert(table="items", columns=columns, values=parsed_items, conflict_columns=["item_id"])`
3. Log the result: `self.logger.info(f"Upserted {count} items")`
4. Return the count

**Why upsert?** On first run, all items are new (INSERT). On subsequent runs, most items already exist. Upsert handles both cases in one query. New items get inserted, existing items get their `last_updated` and any changed fields updated.

---

### Method: `run(self) -> None`

**What it does:** The main entry point. Orchestrates fetch → parse → save. This is what your scheduler calls.

**Parameters:** None

**Returns:** None

**Implementation steps:**
1. Log start: `self.logger.info("Starting item metadata collection")`
2. `raw_items = self.fetch_items()`
3. `parsed_items = self.parse_items(raw_items)`
4. `count = self.save_items(parsed_items)`
5. Update collection status (write to `collection_status` table):
   ```python
   self.db.upsert(
       table="collection_status",
       columns=["collector_name", "last_success", "failure_count"],
       values=[("items", datetime.now(timezone.utc), 0)],
       conflict_columns=["collector_name"]
   )
   ```
6. Wrap the whole thing in `try/except` — on failure:
   - Log the error
   - Update `collection_status` with `last_failure`, increment `failure_count`, set `last_error`
   - Don't re-raise (the scheduler should keep running even if one collection fails)

---

## Full Method Summary

| Method | Purpose | Returns |
|--------|---------|---------|
| `__init__(db)` | Store DB ref, create HTTP session with User-Agent | None |
| `fetch_items()` | GET `/mapping`, return raw JSON | `list[dict]` |
| `parse_items(raw_items)` | Transform dicts into DB-ready tuples | `list[tuple]` |
| `save_items(parsed_items)` | Upsert tuples into `items` table | row count |
| `run()` | Orchestrate fetch → parse → save + status tracking | None |

## Dependencies

```toml
requests = "^2.31"     # HTTP client
```
