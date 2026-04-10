import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from packages.collector.collectors.backfill import BackfillService
from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector
from packages.collector.collectors.prices_5min import PriceCollector5Min
from packages.collector.collectors.prices_1hr import PriceCollector1hr

EST = ZoneInfo("America/New_York")


class ESTFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=EST)
        return dt.strftime(datefmt or "%Y-%m-%d %I:%M:%S %p %Z")


def main() -> None:
    _handler = logging.StreamHandler()
    _handler.setFormatter(ESTFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
    logger = logging.getLogger(__name__)

    # Initialize database connection
    db = DatabaseConnection()
    logger.info("Database connection pool initialized")

    # Fetch item metadata once at startup
    item_collector = ItemCollector(db)
    item_collector.run()

    # Start price collectors in separate threads
    collector_5min = PriceCollector5Min(db)
    collector_1hr = PriceCollector1hr(db)

    thread_5min = threading.Thread(target=collector_5min.run_loop)
    thread_1hr = threading.Thread(target=collector_1hr.run_loop)

    # Start backfill process
    backfill_service = BackfillService(db)

    thread_backfill_5min = threading.Thread(target=backfill_service.run, args=("prices_5min",), daemon=True)
    thread_backfill_1hr = threading.Thread(target=backfill_service.run, args=("prices_1hr",), daemon=True)

    thread_backfill_5min.start()
    thread_backfill_1hr.start()

    thread_5min.start()
    thread_1hr.start()

    logger.info("Started price collection threads")

    # Keep the main thread alive
    try:
        thread_5min.join()
        thread_1hr.join()
        thread_backfill_5min.join()
        thread_backfill_1hr.join()
    except KeyboardInterrupt:
        logger.info("Shutting down collector...")
        db.close()


if __name__ == "__main__":
    main()
