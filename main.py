"""Entry point for the IT Service Desk application."""

import argparse
import logging

from cli.menu import run_menu
from database.db_manager import DatabaseManager
from web.server import run_server


def main() -> None:
    """Initialize persistence and start either the CLI or web dashboard."""
    parser = argparse.ArgumentParser(description="Local IT service desk and incident triage.")
    parser.add_argument(
        "--local-sqlite",
        metavar="PATH",
        help="Use a local SQLite database instead of Neon (development/testing only).",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the local web dashboard instead of the terminal menu.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Web bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Web port (default: 8000).")
    arguments = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = (
        DatabaseManager(database_path=arguments.local_sqlite)
        if arguments.local_sqlite
        else DatabaseManager()
    )
    if arguments.web:
        run_server(database, arguments.host, arguments.port)
    else:
        run_menu(database)


if __name__ == "__main__":
    main()
