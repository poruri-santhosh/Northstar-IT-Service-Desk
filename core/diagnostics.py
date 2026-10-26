"""Cross-platform network checks used to add context to triage logs."""

import platform
import re
import socket
import subprocess
from typing import List

DIAGNOSTIC_HOST = "login.microsoftonline.com"
_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")


def ping_reachability(host: str = DIAGNOSTIC_HOST) -> str:
    """Run one bounded OS ping without invoking a command shell."""
    if not _HOST_PATTERN.fullmatch(host) or host.startswith("-"):
        raise ValueError("Host must be a valid DNS name or IP address.")

    if platform.system().lower() == "windows":
        command = ["ping", "-n", "1", "-w", "2000", host]
    else:
        command = ["ping", "-c", "1", "-W", "2", host]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except FileNotFoundError:
        return "Ping unavailable: the operating-system ping command was not found."
    except subprocess.TimeoutExpired:
        return f"Ping timed out while checking {host}."
    except OSError as error:
        return f"Ping could not run: {error}"

    if result.returncode == 0:
        return f"Ping reachable: {host} responded."
    return f"Ping unreachable: {host} did not respond."


def resolve_dns(host: str = DIAGNOSTIC_HOST) -> str:
    """Resolve a host with the system resolver and return a concise result."""
    if not _HOST_PATTERN.fullmatch(host) or host.startswith("-"):
        raise ValueError("Host must be a valid DNS name or IP address.")

    try:
        addresses = sorted(
            {
                result[4][0]
                for result in socket.getaddrinfo(
                    host, None, type=socket.SOCK_STREAM
                )
            }
        )
    except socket.gaierror as error:
        return f"DNS resolution failed for {host}: {error}"
    except OSError as error:
        return f"DNS lookup could not run: {error}"

    return f"DNS resolved {host}: {', '.join(addresses)}"


def run_diagnostics() -> str:
    """Run the requested DNS and ping checks and combine them into a log."""
    results: List[str] = [
        ping_reachability(DIAGNOSTIC_HOST),
        resolve_dns(DIAGNOSTIC_HOST),
    ]
    return "\n".join(results)
