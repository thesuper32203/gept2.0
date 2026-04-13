CREATE EXTENSION IF NOT EXISTS timescaledb;

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
SELECT create_hypertable('prices_5min', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => true);

-- Index for fast lookups: "get all prices for item X between time A and B"
CREATE INDEX IF NOT EXISTS idx_prices_5min_item_time ON prices_5min (item_id, time DESC);


CREATE TABLE IF NOT EXISTS prices_1hr (
    time            TIMESTAMPTZ     NOT NULL,
    item_id         INTEGER         NOT NULL,
    avg_high_price  BIGINT,
    avg_low_price   BIGINT,
    high_volume     INTEGER,
    low_volume      INTEGER
);

SELECT create_hypertable('prices_1hr', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => true);

CREATE INDEX IF NOT EXISTS idx_prices_1hr_item_time ON prices_1hr (item_id, time DESC);


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

CREATE TABLE IF NOT EXISTS collection_status (
    collector_name  TEXT            PRIMARY KEY,
    last_success    TIMESTAMPTZ     NOT NULL,
    last_failure    TIMESTAMPTZ,
    failure_count   INTEGER         NOT NULL DEFAULT 0,
    last_error      TEXT
);