import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from packages.collector.db.connection import DatabaseConnection

EST = ZoneInfo("America/New_York")

BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
FIVE_MIN_ENDPOINT: str = f"{BASE_URL}/5m"
ONE_HOUR_ENDPOINT: str = f"{BASE_URL}/1h"
USER_AGENT: str = "gept2.0 - your_contact_info"
REQUEST_TIMEOUT: int = 30
DELAY_BETWEEN_REQUESTS: float = 1.0             # Seconds between timestamp requests
BACKFILL_DAYS: int = 90                         # How many days back to backfill (from today)
FIVE_MIN_INTERVAL: int = 300                    # Seconds between 5-min windows
ONE_HOUR_INTERVAL: int = 3600                   # Seconds between 1-hour windows

class BackfillService:
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

    def get_item_ids(self) -> list[Any]:

        rows = self.db.execute_query(
            "SELECT item_id from items ORDER BY item_id ASC"
        )

        return [row[0] for row in rows]

    def get_earliest_timestamp(self, table:str) -> int | None:

        oldest_timestamp = self.db.execute_query(f"SELECT MIN(EXTRACT(EPOCH FROM time)) FROM {table}")
        return int(oldest_timestamp[0][0]) if oldest_timestamp else None

    def calculate_timestamp_range(self, table: str, interval: int) -> list[int]:

        earliest = self.get_earliest_timestamp(table)
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(days=BACKFILL_DAYS)
        cutoff_ts = int(cutoff_time.timestamp())

        if earliest is None:
            start_ts = int(now.timestamp())
        else:
            start_ts = earliest - interval

        timestamp = []
        current_ts = start_ts

        while current_ts >= cutoff_ts:
            timestamp.append(current_ts)
            current_ts -= interval
        logging.info(f"Generated {len(timestamp)} timestamps to backfill, covering {len(timestamp) * interval / 86400:.1f} days")

        return timestamp

    def fetch_prices_at_timestamp(self, timestamp: int, endpoint:str) -> dict:

        params = {"timestamp": timestamp}
        response = self.session.get(endpoint, params=params,headers={"User-Agent": USER_AGENT})
        return response.json()

    def parse_prices(self, api_response: dict) -> list[tuple]:
        prices = api_response.get("data", {})
        unix_ts = api_response.get("timestamp", 0)
        snapshot_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)

        rows = []
        for item_id, price_data in prices.items():
            row = (
                snapshot_time,
                int(item_id),
                price_data.get("avgHighPrice"),
                price_data.get("avgLowPrice"),
                price_data.get("highPriceVolume",0),
                price_data.get("lowPriceVolume",0),
            )
            rows.append(row)
        return rows

    def save_prices(self, table: str, rows: list[tuple]) -> int:

        columns = ["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]
        count = self.db.bulk_insert(table=table, columns=columns, values=rows)
        return count

    def run(self, table: str) -> None:

        endpoint, interval = (
            (FIVE_MIN_ENDPOINT, 300)
            if table == "prices_5min"
            else (ONE_HOUR_ENDPOINT, 3600)
        )

        logging.info(f"Fetching prices at {endpoint}")

        timestamps = self.calculate_timestamp_range(table, interval)
        start_readable = datetime.fromtimestamp(timestamps[0], tz=EST).strftime("%Y-%m-%d %I:%M:%S %p %Z")
        end_readable = datetime.fromtimestamp(timestamps[-1], tz=EST).strftime("%Y-%m-%d %I:%M:%S %p %Z")
        logging.info(f"Fetched {len(timestamps)} timestamps resuming from {start_readable} to {end_readable}")

        logging.info(f"Starting backfill for {table}, {len(timestamps)} timestamps to fetch")
        total_rows = 0

        for i, ts in enumerate(timestamps):
            api_response = self.fetch_prices_at_timestamp(ts, endpoint)
            rows = self.parse_prices(api_response)
            count = self.save_prices(table, rows)
            total_rows += count

            if (i + 1) % 100 == 0:
                hours_elapsed = (i + 1) * interval / 3600
                self.logger.info(f"{table} Progress: {i + 1}/{len(timestamps)}, {total_rows} rows, ~{hours_elapsed:.1f}h of data")

            time.sleep(DELAY_BETWEEN_REQUESTS)


    #INFO:root:Fetched 24834 timestamps resuming from 1775436300 to 1767986400
    #INFO:root:Fetched 24308 timestamps resuming from 1775278800 to 1767986700

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = DatabaseConnection()
    bs = BackfillService(
        db=db,
    )
    bs.run("prices_5min")