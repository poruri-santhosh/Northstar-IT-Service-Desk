"""Focused tests for triage rules, SQLite persistence, and HTTP endpoints."""

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path

from http.server import ThreadingHTTPServer

from core.triage_engine import calculate_priority_and_sla
from database.db_manager import DatabaseManager
from models.ticket import Ticket
from web.server import make_handler


class TriageTests(unittest.TestCase):
    def test_priority_keywords_and_sla_deadlines(self) -> None:
        created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cases = (
            ("Company outage", "P1", 2),
            ("VPN is unavailable", "P2", 4),
            ("VPN access is down during an outage", "P1", 2),
            ("MFA prompt is not arriving", "P2", 4),
            ("Outlook calendar sync", "P2", 4),
            ("Need a new keyboard", "P3", 8),
        )
        for description, expected_priority, hours in cases:
            with self.subTest(description=description):
                priority, deadline = calculate_priority_and_sla(description, created)
                self.assertEqual(priority, expected_priority)
                self.assertEqual(deadline, created + timedelta(hours=hours))

    def test_keyword_matching_does_not_match_substrings(self) -> None:
        priority, _ = calculate_priority_and_sla("The downlink report is missing")
        self.assertEqual(priority, "P3")


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(
            str(Path(self.temp_directory.name) / "tickets.sqlite3")
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _ticket(self, ticket_id: str, priority: str) -> Ticket:
        now = datetime.now(timezone.utc)
        return Ticket(
            ticket_id=ticket_id,
            reporter_name="Casey Example",
            department="IT",
            category="Network",
            issue_description="Connection unavailable",
            priority_level=priority,
            sla_deadline=now + timedelta(hours=2),
            diagnostic_result="Diagnostics unavailable in test.",
            ticket_status="Open",
            created_at=now,
            resolution_notes=None,
        )

    def test_sorted_queries_and_status_updates(self) -> None:
        self.database.insert_ticket(self._ticket("LOW", "P3"))
        self.database.insert_ticket(self._ticket("HIGH", "P1"))
        self.assertEqual(
            [ticket.ticket_id for ticket in self.database.list_tickets()],
            ["HIGH", "LOW"],
        )
        self.assertTrue(self.database.update_ticket("HIGH", "Resolved", "Restored."))
        self.assertEqual(self.database.list_tickets("Resolved")[0].ticket_id, "HIGH")
        self.assertEqual(self.database.get_ticket("HIGH").resolution_notes, "Restored.")
        self.assertFalse(self.database.update_ticket("MISSING", "Open"))


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(
            str(Path(self.temp_directory.name) / "tickets.sqlite3")
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection(*self.server.server_address)

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_directory.cleanup()

    def test_create_list_and_update_ticket(self) -> None:
        body = json.dumps({
            "reporter_name": "Sam Example",
            "department": "Engineering",
            "category": "Network",
            "issue_description": "VPN is unavailable",
        })
        self.connection.request(
            "POST", "/api/tickets", body, {"Content-Type": "application/json"}
        )
        response = self.connection.getresponse()
        created = json.loads(response.read())
        self.assertEqual(response.status, 201)
        ticket_id = created["ticket"]["ticket_id"]
        self.assertEqual(created["ticket"]["priority_level"], "P2")

        self.connection.request("GET", "/api/tickets")
        response = self.connection.getresponse()
        listing = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(listing["tickets"][0]["ticket_id"], ticket_id)

        update = json.dumps({"ticket_status": "Resolved", "resolution_notes": "Restored."})
        self.connection.request(
            "PATCH",
            f"/api/tickets/{ticket_id}",
            update,
            {"Content-Type": "application/json"},
        )
        response = self.connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(response.read())["ticket"]["ticket_status"], "Resolved"
        )

    def test_invalid_ticket_body_is_rejected(self) -> None:
        self.connection.request(
            "POST",
            "/api/tickets",
            '{"reporter_name":""}',
            {"Content-Type": "application/json"},
        )
        response = self.connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 400)
        self.assertIn("reporter_name", payload["error"])

    def test_dashboard_and_assets_are_served_locally(self) -> None:
        self.connection.request("GET", "/")
        response = self.connection.getresponse()
        page = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Northstar", page)
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")

        self.connection.request("GET", "/static/app.js")
        response = self.connection.getresponse()
        script = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("fetch", script)


if __name__ == "__main__":
    unittest.main()
