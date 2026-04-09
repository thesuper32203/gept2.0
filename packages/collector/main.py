import logging
import threading
from packages.collector.db.connection import DatabaseConnection
from packages.collector.collectors.items import ItemCollector
from packages.collector.collectors.prices_5min import PriceCollector5Min
from packages.collector.collectors.prices_1hr import PriceCollector1hr


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
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

    thread_5min = threading.Thread(target=collector_5min.run_loop, daemon=True)
    thread_1hr = threading.Thread(target=collector_1hr.run_loop, daemon=True)

    thread_5min.start()
    thread_1hr.start()

    logger.info("Started price collection threads")

    # Keep the main thread alive
    try:
        thread_5min.join()
        thread_1hr.join()
    except KeyboardInterrupt:
        logger.info("Shutting down collector...")
        db.close()


if __name__ == "__main__":
    main()
