"""Local HTTP server for the responsive service desk dashboard."""

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Type
from urllib.parse import parse_qs, urlsplit

import psycopg

from core.diagnostics import run_diagnostics
from core.triage_engine import calculate_priority_and_sla
from database.db_manager import DatabaseManager
from models.ticket import Ticket

LOGGER = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
_VALID_STATUSES = {"Open", "In Progress", "Resolved"}
_MAX_BODY_SIZE = 16_384
_TICKET_PATH = re.compile(r"^/api/tickets/([A-Za-z0-9_-]{1,64})$")


def _ticket_payload(ticket: Ticket) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "reporter_name": ticket.reporter_name,
        "department": ticket.department,
        "category": ticket.category,
        "issue_description": ticket.issue_description,
        "priority_level": ticket.priority_level,
        "sla_deadline": ticket.sla_deadline.isoformat(),
        "diagnostic_result": ticket.diagnostic_result,
        "ticket_status": ticket.ticket_status,
        "created_at": ticket.created_at.isoformat(),
        "resolution_notes": ticket.resolution_notes,
    }


def make_handler(database: DatabaseManager) -> Type[BaseHTTPRequestHandler]:
    """Bind a database manager to a request handler class."""

    class ServiceDeskHandler(BaseHTTPRequestHandler):
        server_version = "ServiceDesk/1.0"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _read_json(self) -> Dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isdigit():
                raise ValueError("A valid Content-Length header is required.")
            length = int(raw_length)
            if length > _MAX_BODY_SIZE:
                raise OverflowError("Request body is too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def _serve_static(self, path: str) -> None:
            static_file = _STATIC_FILES.get(path)
            if static_file is None:
                self._json(404, {"error": "Not found."})
                return
            filename, content_type = static_file
            try:
                body = (_STATIC_DIR / filename).read_bytes()
            except OSError:
                LOGGER.exception("Could not read dashboard asset %s", filename)
                self._json(500, {"error": "Dashboard asset is unavailable."})
                return
            self._send(200, body, content_type)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path in _STATIC_FILES:
                self._serve_static(parsed.path)
                return
            if parsed.path != "/api/tickets":
                self._json(404, {"error": "Not found."})
                return
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            if status not in (None, "") and status not in _VALID_STATUSES:
                self._json(400, {"error": "Invalid ticket status filter."})
                return
            try:
                tickets = database.list_tickets(status or None)
            except (OSError, psycopg.Error, sqlite3.Error):
                LOGGER.exception("Could not list tickets")
                self._json(500, {"error": "Tickets could not be loaded."})
                return
            self._json(200, {"tickets": [_ticket_payload(item) for item in tickets]})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/tickets":
                self._json(404, {"error": "Not found."})
                return
            try:
                payload = self._read_json()
                required = ("reporter_name", "department", "category", "issue_description")
                values: Dict[str, str] = {}
                for field in required:
                    value = payload.get(field)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"{field} is required.")
                    if len(value.strip()) > (2000 if field == "issue_description" else 200):
                        raise ValueError(f"{field} is too long.")
                    values[field] = value.strip()
                created_at = datetime.now().astimezone()
                priority, deadline = calculate_priority_and_sla(
                    values["issue_description"], created_at
                )
                ticket = Ticket(
                    ticket_id=uuid.uuid4().hex[:12].upper(),
                    reporter_name=values["reporter_name"],
                    department=values["department"],
                    category=values["category"],
                    issue_description=values["issue_description"],
                    priority_level=priority,
                    sla_deadline=deadline,
                    diagnostic_result=run_diagnostics(),
                    ticket_status="Open",
                    created_at=created_at,
                    resolution_notes=None,
                )
                database.insert_ticket(ticket)
            except OverflowError as error:
                self._json(413, {"error": str(error)})
                return
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
                return
            except (OSError, psycopg.Error, sqlite3.Error):
                LOGGER.exception("Could not create ticket")
                self._json(500, {"error": "Ticket could not be created."})
                return
            self._json(201, {"ticket": _ticket_payload(ticket)})

        def do_PATCH(self) -> None:
            match = _TICKET_PATH.fullmatch(urlsplit(self.path).path)
            if match is None:
                self._json(404, {"error": "Not found."})
                return
            try:
                payload = self._read_json()
                status = payload.get("ticket_status")
                notes = payload.get("resolution_notes")
                if status not in _VALID_STATUSES:
                    raise ValueError("ticket_status must be Open, In Progress, or Resolved.")
                if notes is not None and (
                    not isinstance(notes, str) or len(notes) > 2000
                ):
                    raise ValueError("resolution_notes must be at most 2000 characters.")
                updated = database.update_ticket(match.group(1), status, notes)
            except OverflowError as error:
                self._json(413, {"error": str(error)})
                return
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
                return
            except (OSError, psycopg.Error, sqlite3.Error):
                LOGGER.exception("Could not update ticket")
                self._json(500, {"error": "Ticket could not be updated."})
                return
            if not updated:
                self._json(404, {"error": "Ticket not found."})
                return
            ticket = database.get_ticket(match.group(1))
            if ticket is None:
                self._json(404, {"error": "Ticket not found."})
                return
            self._json(200, {"ticket": _ticket_payload(ticket)})

        def log_message(self, format_string: str, *args: Any) -> None:
            LOGGER.info("%s - %s", self.address_string(), format_string % args)

    return ServiceDeskHandler


def run_server(
    database: DatabaseManager,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Serve the dashboard locally until interrupted."""
    server = ThreadingHTTPServer((host, port), make_handler(database))
    server.daemon_threads = True
    print(f"Dashboard running at http://{host}:{port} (Ctrl+C to return)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        server.server_close()
