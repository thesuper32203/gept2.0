import logging                                  # Log collection events

from packages.collector.collectors.base import BaseCollector
from packages.collector.db.connection import DatabaseConnection

BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
FIVE_MIN_ENDPOINT: str = f"{BASE_URL}/5m"
USER_AGENT: str = "gept2.0 - thesuper322@gmail.com"
REQUEST_TIMEOUT: int = 30                       # Seconds before we give up on a request
COLLECTION_INTERVAL: int = 300                  # Seconds between collections (5 min)
MAX_RETRIES: int = 3                            # How many times to retry a failed request
INITIAL_BACKOFF: float = 5.0                    # Seconds to wait before first retry
TABLE = "prices_5min"
COLLECTOR_NAME = "5min collector"

class PriceCollector5Min(BaseCollector):
    def __init__(self, db:DatabaseConnection):
        super().__init__(
            db=db,
            endpoint=FIVE_MIN_ENDPOINT,
            table=TABLE,
            interval=COLLECTION_INTERVAL,
            collector_name=COLLECTOR_NAME,
            max_retries=MAX_RETRIES,
            initial_backoff=INITIAL_BACKOFF
        )


if __name__ == "__main__":
    db = DatabaseConnection()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    price_5m = PriceCollector5Min(db=db)
    price_5m.run_loop()
