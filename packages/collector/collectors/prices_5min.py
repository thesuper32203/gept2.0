import logging                                  # Log collection events
import time                                     # Track timing, calculate sleep
from datetime import datetime, timezone         # Convert Unix timestamps to Python datetimes
from typing import Any

import requests                                 # HTTP calls to the API

from packages.collector.db.connection import DatabaseConnection

BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
FIVE_MIN_ENDPOINT: str = f"{BASE_URL}/5m"
USER_AGENT: str = "gept2.0 - thesuper322@gmail.com"
REQUEST_TIMEOUT: int = 30                       # Seconds before we give up on a request
COLLECTION_INTERVAL: int = 300                  # Seconds between collections (5 min)
MAX_RETRIES: int = 3                            # How many times to retry a failed request
INITIAL_BACKOFF: float = 5.0                    # Seconds to wait before first retry

class PriceCollector5Min:

    def __init__(self, db:DatabaseConnection):

        self.db = db
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.logger = logging.getLogger(__name__)
        self.consecutive_failers: int = 0
        self.last_success_time: datetime | None = None


    def fetch_prices(self, timestamp: int | None = None) -> dict | None:

        params = {}
        if timestamp is not None:
            params["timestamp"] = timestamp

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(FIVE_MIN_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                self.consecutive_failers = 0
                return response.json()
            except requests.exceptions.RequestException as e:
                wait_time = INITIAL_BACKOFF * (2 ** attempt)
                self.logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed {e}, retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            self.consecutive_failers += 1
        return None

    def parse_prices(self, api_response: dict) -> tuple[datetime, list[tuple]]:

        unix_ts = api_response["timestamp"]
        snapshot_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        rows = []
        data = api_response.get("data", {})

        for item_id_str, price_data in data.items():
            item_id = int(item_id_str)
            row = (
                snapshot_time,
                item_id,
                price_data.get("avgHighPrice"),
                price_data.get("avgLowPrice"),
                price_data.get("highPriceVolume",0),
                price_data.get("lowPriceVolume",0)
            )
            rows.append(row)

        self.logger.info(f"Parsed {len(rows)} items for timestamp {snapshot_time}")
        return (snapshot_time, rows)

    def save_prices(self, rows: list[tuple]) -> int:

        columns = ["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]
        count = self.db.bulk_insert(table="prices_5min", columns=columns, values=rows)
        self.logger.info(f"Successfully inserted {count} items")
        return count

    def is_duplicate(self, snapshot_time: datetime) -> bool:

        result = self.db.execute_query(
            "SELECT 1 FROM prices_5min WHERE time = %s LIMIT 1",
            (snapshot_time,)
        )
        return len(result) > 0

    def run(self):

        try:
            self.logger.info(f"Starting run")
            api_response = self.fetch_prices()
            snapshot_time, rows = self.parse_prices(api_response)
            if self.is_duplicate(snapshot_time):
                self.logger.info(f"Data for {snapshot_time} alreadty exists, skipping")
                return

            count = self.save_prices(rows)
            self.last_success_time = datetime.now(timezone.utc)
            self.db.upsert(
                table="prices_5m",
                columns=["collector_name", "last_success", "failure_count"],
                values=[("items", datetime.now(timezone.utc), 0)],
                conflict_columns=["collector_name"]
            )
            self.logger.info(f"Successfully saved {count} items")
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"Exception while fetching {snapshot_time}: {e}")

    def run_loop(self) -> None:

        self.logger.info(f"Starting 5-minute price collector loop")
        while True:
            start = time.time()
            self.run()
            elapsed = time.time() - start
            sleep_time = max(0, int(COLLECTION_INTERVAL - elapsed))
            self.logger.info(f"Sleeping for {sleep_time} seconds")
            time.sleep(sleep_time)

if __name__ == "__main__":

