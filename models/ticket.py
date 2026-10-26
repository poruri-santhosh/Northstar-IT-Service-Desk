"""Ticket data model shared by the CLI, database, and web application."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Ticket:
    """A service desk incident and its current triage and resolution details."""

    ticket_id: str
    reporter_name: str
    department: str
    category: str
    issue_description: str
    priority_level: str
    sla_deadline: datetime
    diagnostic_result: str
    ticket_status: str
    created_at: datetime
    resolution_notes: Optional[str]
