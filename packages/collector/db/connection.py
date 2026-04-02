import os
from dotenv import load_dotenv
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool as pool
import psycopg2.extras
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]

# load env file
load_dotenv(ROOT_DIR / ".env.local")


class DatabaseConnection -> None:

    def __init__(self):
        self.DB_HOST = os.getenv('DB_HOST')
        self.DB_PORT = os.getenv('DB_PORT')
        self.DB_NAME = os.getenv('DB_NAME')
        self.DB_USER = os.getenv('DB_USER')
        self.DB_PASS = os.getenv('DB_PASS')

        self.conn = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            database=self.DB_NAME,
            user=self.DB_USER,
            password=self.DB_PASS,
            host=self.DB_HOST,
            port=self.DB_PORT,
        )
        self.logger = logging.getLogger(__name__)

print(ROOT_DIR)
print(os.getenv("DB_NAME"))