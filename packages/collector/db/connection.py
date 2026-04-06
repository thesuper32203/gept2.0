import os
from dotenv import load_dotenv
import logging
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.pool as pool
import psycopg2.extras
from psycopg2.extras import execute_values
from psycopg2 import sql



ROOT_DIR = Path(__file__).resolve().parents[3]

# load env file
load_dotenv(ROOT_DIR / ".env.local")


class DatabaseConnection:

    def __init__(self) -> None:
        self.DB_HOST = os.getenv('DB_HOST')
        self.DB_PORT = os.getenv('DB_PORT')
        self.DB_NAME = os.getenv('DB_NAME')
        self.DB_USER = os.getenv('DB_USER')
        self.DB_PASS = os.getenv('DB_PASS')

        self.pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            database=self.DB_NAME,
            user=self.DB_USER,
            password=self.DB_PASS,
            host=self.DB_HOST,
            port=self.DB_PORT,
        )
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def get_cursor(self):
        conn = self.pool.getconn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except psycopg2.Error as e:
            conn.rollback()
            self.logger.error(e)
            raise
        finally:
            cursor.close()
            self.pool.putconn(conn)


    def bulk_insert(self, table: str, columns: list[str], values: list[tuple]) -> int:

        if not values:
            return 0

        columns_identifiers = [sql.Identifier(col) for col in columns]
        query = sql.SQL("INSERT INTO {table} ({fields}) VALUES %s").format(
            table=sql.Identifier(table),
            fields=sql.SQL(",").join(columns_identifiers),
        )

        with self.get_cursor() as cursor:
            execute_values(cursor, query, values, page_size=1000)
            return cursor.rowcount

    def upsert(
            self,
            table: str,
            columns: list[str],
            values: list[tuple],
            conflict_columns: list[str]
    ) -> int:

        if not values:
            return 0
        column_identifier = [sql.Identifier(col) for col in columns]
        conflict_identifier = [sql.Identifier(col) for col in conflict_columns]

        update_columns = [col for col in columns if col not in conflict_columns]
        update_assignments = [
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(col))
            for col in update_columns
        ]

        query = sql.SQL("""
            INSERT INTO {table} ({columns}) 
            VALUES %s
            ON CONFLICT ({conflict_columns}) 
            DO UPDATE SET {updates}
        """).format(
            table=sql.Identifier(table),
            columns=sql.SQL(",").join(column_identifier),
            conflict_columns=sql.SQL(",").join(conflict_identifier),
            updates=sql.SQL(",").join(update_assignments),
        )

        with self.get_cursor() as cursor:
            execute_values(cursor, query, values, page_size=1000)
            return cursor.rowcount


    def execute_query(self, query: str, params: tuple | None = None) -> list[tuple] | None:
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            try:
                return cursor.fetchall()
            except psycopg2.ProgrammingError:
                return None

    def close(self) -> None:
        self.pool.closeall()
