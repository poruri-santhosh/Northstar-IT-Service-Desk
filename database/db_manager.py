"""Neon PostgreSQL persistence with an explicit SQLite development option."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

from models.ticket import Ticket


# Load environment variables from the project's .env file.
# Searches the current working directory and parent directories.
load_dotenv()


class DatabaseManager:
    """Create and query the service desk database.

    Neon PostgreSQL is the default backend, configured using
    NEON_DATABASE_URL in the .env file.

    Passing database_path explicitly selects SQLite for development
    and tests.
    """

    def __init__(
        self,
        database_path: Optional[str] = None,
        *,
        database_url: Optional[str] = None,
    ) -> None:

        if database_url and database_path:
            raise ValueError(
                "Choose Neon PostgreSQL or SQLite, not both."
            )

        configured_url = (
            database_url
            if database_url is not None
            else None
            if database_path
            else os.environ.get("NEON_DATABASE_URL")
        )

        if not configured_url and not database_path:
            raise ValueError(
                "NEON_DATABASE_URL is missing. "
                "Add it to your .env file or environment."
            )

        self.database_url = configured_url
        self.database_path = (
            Path(database_path) if database_path else None
        )

        self._is_postgres = configured_url is not None
        self._placeholder = "%s" if self._is_postgres else "?"

        if self.database_path is not None:
            self.database_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        self.initialize_database()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Open a database connection and manage its transaction."""

        if self._is_postgres:
            if self.database_url is None:
                raise ValueError(
                    "A Neon PostgreSQL connection URL is required."
                )

            connection = psycopg.connect(
                self.database_url,
                sslmode="require",
                connect_timeout=10,
                row_factory=dict_row,
            )

        else:
            connection = sqlite3.connect(
                str(self.database_path),
                timeout=10,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_database(self) -> None:
        """Create the tickets table and its status/priority index."""

        timestamp_type = (
            "TIMESTAMPTZ" if self._is_postgres else "TEXT"
        )

        with self._connection() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    reporter_name TEXT NOT NULL,
                    department TEXT NOT NULL,
                    category TEXT NOT NULL,
                    issue_description TEXT NOT NULL,
                    priority_level TEXT NOT NULL
                        CHECK (
                            priority_level IN ('P1', 'P2', 'P3')
                        ),
                    sla_deadline {timestamp_type} NOT NULL,
                    diagnostic_result TEXT NOT NULL,
                    ticket_status TEXT NOT NULL
                        CHECK (
                            ticket_status IN (
                                'Open',
                                'In Progress',
                                'Resolved'
                            )
                        ),
                    created_at {timestamp_type} NOT NULL,
                    resolution_notes TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_tickets_status_priority
                ON tickets (
                    ticket_status,
                    priority_level,
                    sla_deadline
                )
                """
            )

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        """Convert a database timestamp to a Python datetime."""

        if isinstance(value, datetime):
            return value

        return datetime.fromisoformat(str(value))

    @classmethod
    def _to_ticket(cls, row: Any) -> Ticket:
        """Convert a database row into a Ticket object."""

        return Ticket(
            ticket_id=row["ticket_id"],
            reporter_name=row["reporter_name"],
            department=row["department"],
            category=row["category"],
            issue_description=row["issue_description"],
            priority_level=row["priority_level"],
            sla_deadline=cls._timestamp(row["sla_deadline"]),
            diagnostic_result=row["diagnostic_result"],
            ticket_status=row["ticket_status"],
            created_at=cls._timestamp(row["created_at"]),
            resolution_notes=row["resolution_notes"],
        )

    def insert_ticket(self, ticket: Ticket) -> None:
        """Insert a ticket using parameterized SQL."""

        placeholders = ", ".join([self._placeholder] * 11)

        sla_deadline = (
            ticket.sla_deadline
            if self._is_postgres
            else ticket.sla_deadline.isoformat()
        )

        created_at = (
            ticket.created_at
            if self._is_postgres
            else ticket.created_at.isoformat()
        )

        with self._connection() as connection:
            connection.execute(
                f"""
                INSERT INTO tickets (
                    ticket_id,
                    reporter_name,
                    department,
                    category,
                    issue_description,
                    priority_level,
                    sla_deadline,
                    diagnostic_result,
                    ticket_status,
                    created_at,
                    resolution_notes
                )
                VALUES ({placeholders})
                """,
                (
                    ticket.ticket_id,
                    ticket.reporter_name,
                    ticket.department,
                    ticket.category,
                    ticket.issue_description,
                    ticket.priority_level,
                    sla_deadline,
                    ticket.diagnostic_result,
                    ticket.ticket_status,
                    created_at,
                    ticket.resolution_notes,
                ),
            )

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Return a ticket by ID, or None if it does not exist."""

        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM tickets
                WHERE ticket_id = {self._placeholder}
                """,
                (ticket_id,),
            ).fetchone()

        return self._to_ticket(row) if row is not None else None

    def list_tickets(
        self,
        status: Optional[str] = None,
    ) -> List[Ticket]:
        """List tickets by priority, SLA deadline, and creation time."""

        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM tickets
                WHERE (
                    {self._placeholder} IS NULL
                    OR ticket_status = {self._placeholder}
                )
                ORDER BY
                    CASE priority_level
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        ELSE 3
                    END,
                    sla_deadline ASC,
                    created_at DESC
                """,
                (status, status),
            ).fetchall()

        return [self._to_ticket(row) for row in rows]

    def update_ticket(
        self,
        ticket_id: str,
        status: str,
        resolution_notes: Optional[str] = None,
    ) -> bool:
        """Update a ticket's status and optionally its resolution notes."""

        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE tickets
                SET ticket_status = {self._placeholder},
                    resolution_notes = COALESCE(
                        {self._placeholder},
                        resolution_notes
                    )
                WHERE ticket_id = {self._placeholder}
                """,
                (status, resolution_notes, ticket_id),
            )

        return cursor.rowcount == 1
