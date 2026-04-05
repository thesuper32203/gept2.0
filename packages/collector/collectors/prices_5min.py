import logging                                  # Log collection events
import time                                     # Track timing, calculate sleep
from datetime import datetime, timezone         # Convert Unix timestamps to Python datetimes

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
