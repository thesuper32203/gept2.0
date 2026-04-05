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


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    db = DatabaseConnection()
    print("connected to db")
    conn = PriceCollector5Min(db)
    print("Connected to endpoints")
    items = conn.fetch_prices()
    print("Fetched prices")
    print(items)
    parsed = conn.parse_prices(items)
    print(parsed)
