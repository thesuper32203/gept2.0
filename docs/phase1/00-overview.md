# Phase 1 Overview — Data Collection Layer

## What You're Building

A data pipeline that continuously collects OSRS Grand Exchange price data from the Wiki API and stores it in a time-series database. This is the foundation everything else (ML, recommendations, dashboard) depends on.

## Build Order & File Structure

Build these files in this exact order — each one depends on the ones before it:

```
gept2.0/
├── packages/
│   └── collector/
│       ├── __init__.py                          (empty file, marks this as a Python package)
│       ├── db/
│       │   ├── __init__.py                      (empty file)
│       │   ├── schema.sql                       (Step 1)
│       │   └── connection.py                    (Step 2) — Class: DatabaseConnection
│       ├── collectors/
│       │   ├── __init__.py                      (empty file)
│       │   ├── base.py                          (Step 5 option) — Class: BasePriceCollector
│       │   ├── items.py                         (Step 3) — Class: ItemCollector
│       │   ├── prices_5min.py                   (Step 4) — Class: PriceCollector5Min
│       │   └── prices_1hr.py                    (Step 5) — Class: PriceCollector1Hr
│       └── main.py                              (Step 7) — Entry point, function: main()
├── docker-compose.yml                           (Step 6)
├── Dockerfile                                   (inside packages/collector/ or at root)
├── pyproject.toml                               (Step 7)
├── .env                                         (Step 6)
├── .gitignore                                   (Step 6)
└── README.md
```

| # | File | What It Does | Depends On | Class/Function |
|---|------|-------------|-----------|--------|
| 1 | `packages/collector/db/schema.sql` | Creates database tables | Nothing (run first) | — (SQL, not Python) |
| 2 | `packages/collector/db/connection.py` | Connects Python to the database | schema.sql (tables must exist) | `DatabaseConnection` |
| 3 | `packages/collector/collectors/items.py` | Fetches item metadata (names, buy limits) | connection.py | `ItemCollector` |
| 4 | `packages/collector/collectors/prices_5min.py` | Polls 5-min prices every 300s | connection.py | `PriceCollector5Min` |
| 5a | `packages/collector/collectors/base.py` | Shared base class for price collectors | connection.py | `BasePriceCollector` |
| 5b | `packages/collector/collectors/prices_1hr.py` | Polls 1-hour prices every 3600s | base.py (recommended) or connection.py | `PriceCollector1Hr` |
| 6 | `packages/collector/backfill.py` | Pulls historical data for ML training | connection.py, items.py | `BackfillService` |
| 7 | `packages/collector/main.py` | Entry point that starts all collectors | All of the above | `main()` function |
| 8 | `docker-compose.yml` | Orchestrates everything | All of the above | — (YAML config) |
| 9 | `packages/collector/Dockerfile` | Docker image definition | All of the above | — (Docker config) |
| 10 | `pyproject.toml` | Python dependency management | Nothing (can create anytime) | — (Poetry config) |
| 11 | `.env` | Database credentials (never commit!) | Nothing (can create anytime) | — (Environment vars) |

## API You're Talking To

**Base URL**: `https://prices.runescape.wiki/api/v1/osrs/`

**CRITICAL**: You MUST set a custom `User-Agent` header on every request. The Wiki blocks default user agents like `python-requests`, `Python-urllib`, `curl/X.X`. Use something descriptive like `gept2.0 - your_contact_info`.

### Endpoints

| Endpoint | Returns | Poll Frequency |
|----------|---------|---------------|
| `/5m` | All items' avg prices + volume for the last 5 min | Every 300 seconds |
| `/1h` | All items' avg prices + volume for the last hour | Every 3600 seconds |
| `/mapping` | Item metadata (name, id, buy limit, members, alch values) | Once at startup, then daily |
| `/timeseries?id=<item_id>&timestep=5m` | Historical 5-min data for ONE item (~365 entries) | Backfill only |

### Response Shapes (real data from the API)

**`/5m` and `/1h` response:**
```json
{
  "timestamp": 1774990800,
  "data": {
    "2": {
      "avgHighPrice": 297,
      "highPriceVolume": 72389,
      "avgLowPrice": 292,
      "lowPriceVolume": 2902
    },
    "6": {
      "avgHighPrice": 218341,
      "highPriceVolume": 1,
      "avgLowPrice": null,
      "lowPriceVolume": 0
    }
  }
}
```
- Keys in `data` are item IDs as strings
- `avgHighPrice` = average instant-buy price (what buyers pay to buy immediately)
- `avgLowPrice` = average instant-sell price (what sellers receive when selling immediately)
- `highPriceVolume` = number of items traded at the high price
- `lowPriceVolume` = number of items traded at the low price
- Values can be `null` / `None` if no trades happened in that window

**`/mapping` response:**
```json
[
  {
    "examine": "Fabulously ancient mage protection enchanted in the 3rd Age.",
    "id": 10344,
    "members": true,
    "lowalch": 20200,
    "limit": 8,
    "value": 50500,
    "highalch": 30300,
    "icon": "3rd age amulet.png",
    "name": "3rd age amulet"
  }
]
```
- `id` = unique item ID (integer) — this is the key that links to price data
- `name` = human-readable item name
- `members` = true if members-only item
- `limit` = GE buy limit (max you can buy per 4-hour window)
- `highalch` / `lowalch` = high/low alchemy gold values
- `value` = store price

**`/timeseries` response:**
```json
{
  "itemId": 4151,
  "data": [
    {
      "timestamp": 1774880400,
      "avgHighPrice": 1252484,
      "avgLowPrice": 1228665,
      "highPriceVolume": 4,
      "lowPriceVolume": 6
    }
  ]
}
```
- Returns ~365 entries for `5m` timestep (about 30 hours of data)
- Same price/volume fields as `/5m`
- Each entry has its own `timestamp` (Unix seconds)

## Timestamps

All timestamps from the API are **Unix timestamps in seconds** (not milliseconds). When storing in PostgreSQL with `TIMESTAMPTZ`, you'll convert using:
```python
from datetime import datetime, timezone
dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
```
