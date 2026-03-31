# 01 — Database Schema

**File Location:** `packages/collector/db/schema.sql`

**What You're Writing:** Pure SQL — this is a database migration file, not Python.

**Where It Goes in Your Project:**
```
gept2.0/
└── packages/
    └── collector/
        └── db/
            ├── __init__.py          (empty file)
            └── schema.sql           ← YOU ARE HERE
```

## What This File Does

Defines all the database tables for Phase 1. You run this SQL once against your PostgreSQL + TimescaleDB instance to create the tables. After that, your Python code writes to them.

## Why TimescaleDB?

Regular PostgreSQL stores data in rows. When you have millions of price rows and query "give me all 5-min prices for item 4151 in the last 7 days", PostgreSQL scans a lot of data. TimescaleDB adds **hypertables** — it automatically partitions your data by time into chunks (like folders organized by week). Queries on time ranges become dramatically faster because it only looks at the relevant chunks.

You get TimescaleDB by using the `timescale/timescaledb` Docker image instead of plain `postgres`.

---

## Tables

### 1. `prices_5min` — Primary ML Training Data

This is the most important table. Every 5 minutes, your collector inserts one row per traded item.

```sql
CREATE TABLE IF NOT EXISTS prices_5min (
    time            TIMESTAMPTZ     NOT NULL,
    item_id         INTEGER         NOT NULL,
    avg_high_price  BIGINT,
    avg_low_price   BIGINT,
    high_volume     INTEGER,
    low_volume      INTEGER
);

-- Convert to hypertable — TimescaleDB partitions by time automatically
-- chunk_time_interval = 1 day means each internal partition covers 24 hours
SELECT create_hypertable('prices_5min', 'time', chunk_time_interval => INTERVAL '1 day');

-- Index for fast lookups: "get all prices for item X between time A and B"
CREATE INDEX idx_prices_5min_item_time ON prices_5min (item_id, time DESC);
```

**Column breakdown:**

| Column | Type | Maps To API Field | Why |
|--------|------|------------------|-----|
| `time` | `TIMESTAMPTZ` | `timestamp` (converted from Unix) | When this 5-min window started. TimescaleDB partitions on this. |
| `item_id` | `INTEGER` | Key in `data` dict (e.g., `"2"`, `"4151"`) | Which item. Integer, not string — cast from the API response key. |
| `avg_high_price` | `BIGINT` | `avgHighPrice` | Average instant-buy price. `BIGINT` because some items cost over 2.1B (max `INTEGER`). Can be `NULL` if no trades. |
| `avg_low_price` | `BIGINT` | `avgLowPrice` | Average instant-sell price. Can be `NULL`. |
| `high_volume` | `INTEGER` | `highPriceVolume` | Number of items bought at high price. Regular `INTEGER` is fine (max ~2.1B, no item trades that much per 5 min). |
| `low_volume` | `INTEGER` | `lowPriceVolume` | Number of items sold at low price. |

**Why BIGINT for prices?** OSRS item prices can exceed 2,147,483,647 gp (the max for a regular `INTEGER`). Example: 3rd Age Pickaxe can be 2B+. `BIGINT` handles up to 9.2 quintillion — future-proof.

**Why no PRIMARY KEY?** TimescaleDB hypertables don't support standard primary keys across chunks. Instead, we use a unique index if needed. In practice, duplicate prevention is handled in your Python insert logic (upsert pattern).

---

### 2. `prices_1hr` — Long-Term Trend Data

Same structure as `prices_5min` but with a longer chunk interval since data arrives less frequently.

```sql
CREATE TABLE IF NOT EXISTS prices_1hr (
    time            TIMESTAMPTZ     NOT NULL,
    item_id         INTEGER         NOT NULL,
    avg_high_price  BIGINT,
    avg_low_price   BIGINT,
    high_volume     INTEGER,
    low_volume      INTEGER
);

SELECT create_hypertable('prices_1hr', 'time', chunk_time_interval => INTERVAL '7 days');

CREATE INDEX idx_prices_1hr_item_time ON prices_1hr (item_id, time DESC);
```

**Why 7-day chunks?** There are 24 rows per item per day (one per hour) vs 288 for 5-min. Fewer rows = bigger chunks are efficient. 7 days keeps chunk sizes manageable while reducing the total number of partitions.

---

### 3. `items` — Item Metadata

Static-ish data about each item. Updated daily to catch any new items Jagex adds.

```sql
CREATE TABLE IF NOT EXISTS items (
    item_id         INTEGER         PRIMARY KEY,
    name            TEXT            NOT NULL,
    members         BOOLEAN         NOT NULL DEFAULT false,
    buy_limit       INTEGER,
    high_alch       INTEGER,
    low_alch        INTEGER,
    value           INTEGER,
    examine         TEXT,
    icon            TEXT,
    last_updated    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

**Column breakdown:**

| Column | Type | Maps To API Field | Why |
|--------|------|------------------|-----|
| `item_id` | `INTEGER PRIMARY KEY` | `id` | The unique item identifier. Primary key here because this is a regular table (not a hypertable). |
| `name` | `TEXT NOT NULL` | `name` | Human-readable name like "Abyssal whip". |
| `members` | `BOOLEAN` | `members` | Whether the item is members-only. Useful for filtering. |
| `buy_limit` | `INTEGER` | `limit` | Max items purchasable per 4-hour GE window. Critical for recommendation engine later — you can't flip 10,000 of an item with limit 8. |
| `high_alch` / `low_alch` | `INTEGER` | `highalch` / `lowalch` | Alchemy values set a price floor — items rarely sell below high alch value. |
| `value` | `INTEGER` | `value` | Store price. Less useful but good to have. |
| `examine` | `TEXT` | `examine` | Examine text. Mainly for the UI later. |
| `icon` | `TEXT` | `icon` | Wiki icon filename. For displaying item images in the dashboard. |
| `last_updated` | `TIMESTAMPTZ` | N/A (you set this) | Track when metadata was last refreshed. |

---

### 4. `collection_status` — Health Monitoring

Track when each collector last ran successfully. For gap detection and monitoring.

```sql
CREATE TABLE IF NOT EXISTS collection_status (
    collector_name  TEXT            PRIMARY KEY,
    last_success    TIMESTAMPTZ     NOT NULL,
    last_failure    TIMESTAMPTZ,
    failure_count   INTEGER         NOT NULL DEFAULT 0,
    last_error      TEXT
);
```

**Why?** When a collector fails silently (network issue, API down), you need to know. Your health check queries this table: "has `collector_5min` succeeded in the last 10 minutes? If not, something is wrong."

---

## How to Run This

Once your Docker Compose is up and the TimescaleDB container is running:

```bash
# Connect to the database and run the schema
docker compose exec db psql -U gept -d gept -f /docker-entrypoint-initdb.d/schema.sql
```

Or you can mount the schema file to `/docker-entrypoint-initdb.d/` in your `docker-compose.yml` — PostgreSQL automatically runs any `.sql` files in that directory on first startup.

---

## Quick Reference: SQL You'll Use Later

```sql
-- Check if data is being collected
SELECT COUNT(*), MIN(time), MAX(time) FROM prices_5min;

-- Get latest prices for a specific item
SELECT * FROM prices_5min
WHERE item_id = 4151
ORDER BY time DESC
LIMIT 10;

-- Check for collection gaps (more than 5 min between entries)
SELECT time,
       LEAD(time) OVER (ORDER BY time) AS next_time,
       LEAD(time) OVER (ORDER BY time) - time AS gap
FROM prices_5min
WHERE item_id = 4151
ORDER BY time DESC
LIMIT 50;
```
