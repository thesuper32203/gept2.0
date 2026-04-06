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

    def get_already_backfilled(self, table:str) ->set[int]:

        rows = self.db.execute_query(
            "SELECT DISTINCT item_id FROM {table} ORDER BY item_id ASC".format(table=table)
        )
        return set(row[0] for row in rows)

    def fetch_timeseries(self, table:str, timestamp:str) -> list[dict]:

        return list({})

if __name__ == "__main__":
    db = DatabaseConnection()
    backfill = BackfillService(db)
    print(backfill.get_item_ids())
    print(backfill.get_already_backfilled("prices_5min"))