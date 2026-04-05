import logging
import time
from datetime import datetime, timezone

import requests

from packages.collector.db.connection import DatabaseConnection

class BaseCollector:

    def __init__(self, db: DatabaseConnection, endpoint, table, interval, collector_name, max_retries=5, initial_backoff=5.0):
        self.db = db
        self.endpoint = endpoint
        self.table = table
        self.logger = logging.getLogger(collector_name)
        self.interval = interval
        self.collector_name = collector_name
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent" : "GePT 2.0 thesuper322@gmail.com"})
        self.last_success_time = None


    def fetch_prices(self, timestamp: int | None = None) -> dict:

        params = {}
        if timestamp is not None:
            params["timestamp"] = timestamp
        try:
            for attempts in range(self.max_retries):
                response = self.session.get(self.endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                return data
        except Exception as e:
            logging.error(e)
            return {}

    def parse_prices(self, api_response: dict) -> (datetime, list[tuple]):

        unix_ts = api_response["timestamp"]
        snapshot_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        try:
            data = api_response["data"]
            rows = []
            for item_id_str, price_data in data.items():
                item_id = int(item_id_str)
                row = (
                    snapshot_time,
                    item_id,
                    price_data.get("avgHighPrice"),
                    price_data.get("avgLowPrice"),
                    price_data.get("highPriceVolume", 0),
                    price_data.get("lowPriceVolume", 0)
                )
                rows.append(row)

            return (snapshot_time, rows)
        except Exception as e:
            logging.error(e)
            return {}

    def save_prices(self, rows:list[tuple]) -> int:

        try:
            columns = ["time", "item_id", "avg_high_price", "avg_low_price", "high_volume", "low_volume"]
            count = self.db.bulk_insert(table=self.table, columns=columns, values=rows)
            return count
        except Exception as e:
            logging.error(e)

    def is_duplicate(self, snapshot_time:datetime) -> bool:

        result = self.db.execute_query(
            f"SELECT 1 FROM {self.table} WHERE time = %s LIMIT 1",
            (snapshot_time,)
        )
        return len(result) > 0

    def run(self):

        try:
            api_response = self.fetch_prices()
            snapshot_time, rows = self.parse_prices(api_response)

            if self.is_duplicate(snapshot_time):
                self.logger.info(f"Data for {snapshot_time} alreadty exists, skipping")
                return
            count = self.save_prices(rows)
            self.last_success_time = datetime.now(timezone.utc)

            self.db.upsert(
                table="collection_status",
                columns=["collector_name", "last_success", "failure_count"],
                values=[(self.collector_name, self.last_success_time, 0)],
                conflict_columns=["collector_name"]
            )

            self.logger.info(f"Successfully saved {count} items")
        except Exception as e:
            logging.error(e)

    def run_loop(self):

        self.logger.info(f"Starting {self.collector_name} price collector loop")
        while True:
            start = time.time()
            self.run()
            elapsed = time.time() - start
            sleep_time = max(0, int(self.interval - elapsed))
            self.logger.info(f"Sleeping for {sleep_time} seconds")
            time.sleep(sleep_time)
