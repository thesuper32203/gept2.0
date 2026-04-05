import logging
import sys
from datetime import datetime, timezone
from typing import Any

import requests

from packages.collector import db
from packages.collector.db.connection import DatabaseConnection

# constants
BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
MAPPING_ENDPOINT: str = f"{BASE_URL}/mapping"
USER_AGENT: str = "gept2.0 - thesuper322@gmail.com"   # REQUIRED by the Wiki API
REQUEST_TIMEOUT: int = 30                           # Seconds before request fails

class ItemCollector:

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.logger = logging.getLogger(__name__)

    def fetch_item(self) -> Any | None:

        try:
            response = self.session.get(MAPPING_ENDPOINT, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            self.logger.info(f"Fetched {len(data)} items from mapping API")
        except requests.RequestException as e:
            self.logger.exception("Failed to fetch items from mapping API %s", e)
            return None

        return data

database = DatabaseConnection()
item = ItemCollector(database)
if __name__ == "__main__":
    itemMapping = item.fetch_item()
    print(itemMapping)
