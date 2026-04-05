import logging
from datetime import datetime, timezone

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

    def fetch_item(selfself):