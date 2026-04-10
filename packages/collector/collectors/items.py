import logging
import sys
from datetime import datetime, timezone
from typing import Any

import requests

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

    def parse_item(self, items: list[dict]) -> list[tuple] | None:

        cleaned_items = []
        now = datetime.now(timezone.utc)

        for item in items:
            item_id = item.get("id")
            name = item.get("name", "unknown")
            members = item.get("members")
            limit = item.get("limit")
            highalch = item.get("highalch")
            lowalch = item.get("lowalch")
            value = item.get("value")
            examine = item.get("examine")
            icon = item.get("icon")
            clean_item = (item_id, name, members, limit, highalch, lowalch, value, examine, icon, now)
            cleaned_items.append(clean_item)
        return cleaned_items

    def save_item(self, parsed_items: list[tuple]) -> int:

        columns = ["item_id", "name", "members", "buy_limit",
                   "high_alch", "low_alch", "value", "examine",
                   "icon", "last_updated"]
        count = self.db.upsert(table="items", columns=columns, values=parsed_items,conflict_columns=["item_id"])
        self.logger.info(f"Saved {len(parsed_items)} items from mapping API\nUpserted {count}")
        return count

    def run(self) -> None:
        try:
            self.logger.info("Starting item metadata collection")
            raw_items = self.fetch_item()
            if raw_items is None:
                self.logger.error("No items fetched, skipping collection")
                return
            parsed_items = self.parse_item(raw_items)
            count = self.save_item(parsed_items)
            self.db.upsert(
                table="collection_status",
                columns=["collector_name", "last_success", "failure_count"],
                values=[("items", datetime.now(timezone.utc), 0)],
                conflict_columns=["collector_name"]
            )

        except Exception as e:
            self.logger.exception("Failed to collect items from mapping API")
            self.db.execute_query(
                """
                INSERT INTO collection_status (collector_name, last_success, failure_count)
                VALUES (%s,NOW(), 1)
                ON CONFLICT (collector_name)
                    DO UPDATE SET failure_count = collection_status.failure_count + 1
                """,
                ("items",)
            )

