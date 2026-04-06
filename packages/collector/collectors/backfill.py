import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector

BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
TIMESERIES_ENDPOINT: str = f"{BASE_URL}/timeseries"
USER_AGENT: str = "gept2.0 - thesuper322@gmail.com"
REQUEST_TIMEOUT: int = 30
DELAY_BETWEEN_REQUESTS: float = 1.0             # Seconds between items — be respectful
TIMESTEPS: list[str] = ["5m", "1h"]             # Fetch both resolutions
db = DatabaseConnection()
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



if __name__ == "__main__":
    db = DatabaseConnection()
    backfill = BackfillService(db)
    val = backfill.get_earliest_timestamp("prices_1hr")
    print(val)