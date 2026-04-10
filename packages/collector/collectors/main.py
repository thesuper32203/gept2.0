import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


class ESTFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=EST)
        return dt.strftime(datefmt or "%Y-%m-%d %I:%M:%S %p %Z")


# Configure logging before package imports so all module-level loggers inherit this formatter
_handler = logging.StreamHandler()
_handler.setFormatter(ESTFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)

from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector
from packages.collector.collectors.prices_5min import PriceCollector5Min
from packages.collector.collectors.prices_1hr import PriceCollector1hr
from packages.collector.collectors.backfill import BackfillService

if __name__ == "__main__":

    db = DatabaseConnection()

    #items = ItemCollector(db)
    #items.run()

    #collector_5min = PriceCollector5Min(db)
    #collector_1hr = PriceCollector1hr(db)
    #backfill = BackfillService(db)

    #thread_5min = threading.Thread(target=collector_5min.run,)
    #thread_1hr = threading.Thread(target=collector_1hr.run,)
    #thread_5min_backfill = threading.Thread(target=backfill.run, args=("prices_5min",), daemon=True)
    #thread_1hr_backfill = threading.Thread(target=backfill.run, args=("prices_1hr",), daemon=True)

    #thread_1hr.start()
    #thread_1hr_backfill.start()

    #thread_5min_backfill.start()
    #thread_5min.start()

    #thread_5min_backfill.join()
    #thread_5min.join()

    #thread_1hr_backfill.join()
    #thread_1hr.join()
