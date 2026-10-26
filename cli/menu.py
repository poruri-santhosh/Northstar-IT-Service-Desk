"""Interactive CLI for creating, viewing, and updating service tickets."""

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional

from core.diagnostics import run_diagnostics
from core.triage_engine import calculate_priority_and_sla
from database.db_manager import DatabaseManager
from models.ticket import Ticket

LOGGER = logging.getLogger(__name__)
_STATUSES = ("Open", "In Progress", "Resolved")


def _read_required(prompt: str, maximum: int = 200) -> str:
    while True:
        value = input(prompt).strip()
        if value and len(value) <= maximum:
            return value
        print(f"Enter between 1 and {maximum} characters.")


def _format_table(tickets: List[Ticket]) -> None:
    headers = ("ID", "PRIORITY", "STATUS", "REPORTER", "CATEGORY", "SLA DEADLINE")
    rows = [
        (
            ticket.ticket_id[:8],
            ticket.priority_level,
            ticket.ticket_status,
            ticket.reporter_name,
            ticket.category,
            ticket.sla_deadline.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
        for ticket in tickets
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _create_ticket(
    database: DatabaseManager,
    reporter: str,
    department: str,
    category: str,
    description: str,
) -> Ticket:
    created_at = datetime.now().astimezone()
    priority, deadline = calculate_priority_and_sla(description, created_at)
    ticket = Ticket(
        ticket_id=uuid.uuid4().hex[:12].upper(),
        reporter_name=reporter,
        department=department,
        category=category,
        issue_description=description,
        priority_level=priority,
        sla_deadline=deadline,
        diagnostic_result=run_diagnostics(),
        ticket_status="Open",
        created_at=created_at,
        resolution_notes=None,
    )
    database.insert_ticket(ticket)
    return ticket


def inject_sample_data(database: DatabaseManager) -> int:
    """Add three representative incidents once, without duplicate samples."""
    samples = (
        ("Alex Morgan", "Operations", "Network", "Company-wide network outage"),
        ("Jordan Lee", "Finance", "Access", "VPN disconnects when signing in"),
        ("Taylor Reed", "People", "Email", "Outlook calendar is not syncing"),
    )
    existing = {ticket.ticket_id for ticket in database.list_tickets()}
    added = 0
    for index, (reporter, department, category, description) in enumerate(samples, 1):
        ticket_id = f"SAMPLE{index:06d}"
        if ticket_id in existing:
            continue
        created_at = datetime.now().astimezone()
        priority, deadline = calculate_priority_and_sla(description, created_at)
        database.insert_ticket(
            Ticket(
                ticket_id=ticket_id,
                reporter_name=reporter,
                department=department,
                category=category,
                issue_description=description,
                priority_level=priority,
                sla_deadline=deadline,
                diagnostic_result="Sample ticket; diagnostics not run.",
                ticket_status="Open",
                created_at=created_at,
                resolution_notes=None,
            )
        )
        added += 1
    return added


def _update_ticket(database: DatabaseManager) -> None:
    ticket_id = _read_required("Ticket ID: ", maximum=64).upper()
    ticket = database.get_ticket(ticket_id)
    if ticket is None:
        print("Ticket not found.")
        return
    print("Statuses: " + ", ".join(_STATUSES))
    status = _read_required("New status: ", maximum=20).title()
    if status not in _STATUSES:
        print("Invalid status.")
        return
    notes: Optional[str] = None
    if status == "Resolved":
        notes = _read_required("Resolution notes: ", maximum=2000)
    if database.update_ticket(ticket_id, status, notes):
        print("Ticket updated.")


def run_menu(database: DatabaseManager) -> None:
    """Run the command-line menu until the user exits."""
    while True:
        print(
            "\nIT SERVICE DESK\n"
            "1. Create a ticket\n"
            "2. List tickets\n"
            "3. Update ticket status\n"
            "4. Inject sample data\n"
            "5. Launch web dashboard\n"
            "0. Exit"
        )
        choice = input("Choose an option: ").strip()
        try:
            if choice == "1":
                reporter = _read_required("Reporter name: ")
                department = _read_required("Department: ")
                category = _read_required("Category: ")
                description = _read_required("Describe the issue: ", maximum=2000)
                ticket = _create_ticket(
                    database, reporter, department, category, description
                )
                print(
                    f"Created {ticket.ticket_id} | {ticket.priority_level} | "
                    f"due {ticket.sla_deadline.astimezone().strftime('%Y-%m-%d %H:%M')}"
                )
                print(ticket.diagnostic_result)
            elif choice == "2":
                status = input("Filter by status (blank for all): ").strip()
                if status:
                    status = status.title()
                    if status not in _STATUSES:
                        print("Invalid status.")
                        continue
                _format_table(database.list_tickets(status or None))
            elif choice == "3":
                _update_ticket(database)
            elif choice == "4":
                print(f"Added {inject_sample_data(database)} sample ticket(s).")
            elif choice == "5":
                from web.server import run_server

                run_server(database)
            elif choice == "0":
                return
            else:
                print("Choose one of the listed options.")
        except (OSError, ValueError, sqlite3.Error) as error:
            LOGGER.exception("Service desk operation failed")
            print(f"Operation failed: {error}")
        except KeyboardInterrupt:
            print("\nReturning to the menu.")
