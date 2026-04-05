import logging
import time
from datetime import datetime, timezone

import requests

from packages.collector.db.connection import DatabaseConnection

BASE_URL: str = "https://prices.runescape.wiki/api/v1/osrs"
ONE_HOUR_ENDPOINT: str = f"{BASE_URL}/1h"
USER_AGENT: str = "gept2.0 - thesuper322@gmail.com"
REQUEST_TIMEOUT: int = 30
COLLECTION_INTERVAL: int = 3600                  # 1 hour
MAX_RETRIES: int = 3
INITIAL_BACKOFF: float = 10.0                    # Slightly longer initial backoff — less urgency