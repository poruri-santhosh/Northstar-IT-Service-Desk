# Northstar IT Service Desk

A production-oriented incident desk with keyword-based triage, Neon PostgreSQL persistence, a terminal workflow, and a responsive browser dashboard. The web server and dashboard use Python's standard library and browser-native HTML, CSS, and JavaScript. PostgreSQL connectivity uses the `psycopg` driver.

## Run

Requires Python 3.9 or later and a Neon PostgreSQL database.

```powershell
python -m pip install -r requirements.txt
$env:NEON_DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
python main.py
```

Set `NEON_DATABASE_URL` in your shell or deployment secret manager; do not commit database credentials. The connection enforces TLS and a 10-second connection timeout. The terminal menu can create, sort, and update tickets, inject repeat-safe sample data, and launch the dashboard. To start the dashboard directly:

```powershell
python main.py --web
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Use `--host` and `--port` to change the web listener; the default binds to loopback so the dashboard is private to the local machine.

For isolated development or tests, pass an explicit SQLite database path instead:

```powershell
python main.py --local-sqlite .\dev-service-desk.db
```

This local option uses SQLite WAL mode and does not require a database URL.

## Incident triage

The first matching rule determines the SLA: outage or critical is **P1 / 2 hours**; VPN, MFA, or Outlook is **P2 / 4 hours**; down or unavailable is **P1 / 2 hours** when no named P2 category or explicit outage is present; other issues are **P3 / 8 hours**. Priority keywords are matched as whole words. Each new ticket records an operating-system ping attempt and a system DNS lookup for `login.microsoftonline.com`; diagnostic failures are reported in the log instead of interrupting ticket creation.

## Layout

```text
models/ticket.py
database/db_manager.py — Neon PostgreSQL by default; explicit SQLite/WAL for local development.
core/diagnostics.py
core/triage_engine.py
cli/menu.py
web/server.py
web/static/index.html
web/static/styles.css
web/static/app.js
main.py
tests/test_service_desk.py
```

## Tests

```powershell
python -m unittest discover -v
```

## Local API

- `GET /api/tickets` — list tickets, optionally filtered with `?status=Open`.
- `POST /api/tickets` — create a ticket with reporter name, department, category, and issue description.
- `PATCH /api/tickets/{ticket_id}` — update `ticket_status` and optional `resolution_notes`.

The web interface is served by Python's standard-library HTTP server and is intended for local, trusted use; it does not provide user authentication or web-server TLS. The PostgreSQL connection itself requires TLS.
