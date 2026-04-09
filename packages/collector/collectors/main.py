import logging
import threading

from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector
from packages.collector.collectors.prices_5min import PriceCollector5Min
from packages.collector.collectors.prices_1hr import PriceCollector1hr
from packages.collector.collectors.backfill import BackfillService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

db = DatabaseConnection()

items = ItemCollector(db)
items.run()

collector_5min = PriceCollector5Min(db)
collector_1hr = PriceCollector1hr(db)
backfill = BackfillService(db)

thread_5min = threading.Thread(target=collector_5min.run,)
thread_1hr = threading.Thread(target=collector_1hr.run,)
thread_5min_backfill = threading.Thread(target=backfill.run, args="prices_5min")
thread_1hr_backfill = threading.Thread(target=backfill.run, args="prices_1hr")

thread_1hr_backfill.start()
thread_5min_backfill.start()
thread_5min.start()
thread_1hr.start()

thread_1hr.join()
thread_1hr_backfill.join()
thread_5min_backfill.join()
thread_5min.join()