"""Keyword-based incident priority and SLA calculations."""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

_RULES = (
    ("P1", timedelta(hours=2), re.compile(r"\b(outage|critical)\b")),
    ("P2", timedelta(hours=4), re.compile(r"\b(vpn|mfa|outlook)\b")),
)
_DEFAULT_PRIORITY = "P3"
_DEFAULT_SLA = timedelta(hours=8)
_UNAVAILABLE_PATTERN = re.compile(r"\b(down|unavailable)\b")


def calculate_priority_and_sla(
    issue_description: str, created_at: Optional[datetime] = None
) -> Tuple[str, datetime]:
    """Return a priority and deadline using the first matching keyword rule.

    Outages and critical unavailability are P1 (2 hours); VPN, MFA, and
    Outlook incidents are P2 (4 hours); all other incidents are P3 (8 hours).
    """
    timestamp = created_at or datetime.now().astimezone()
    normalized = issue_description.casefold()

    for priority, sla, pattern in _RULES:
        if pattern.search(normalized):
            return priority, timestamp + sla
    if _UNAVAILABLE_PATTERN.search(normalized):
        return "P1", timestamp + timedelta(hours=2)
    return _DEFAULT_PRIORITY, timestamp + _DEFAULT_SLA
