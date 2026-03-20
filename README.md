# ICON Milesight Dashboard

Flask dashboard for Milesight sensor data with:

- live and historical IAQ monitoring
- floor map visualization
- alarm management and guidance workflows
- settings, source mapping, and user management
- SQLite-based local storage

The app supports local development on Windows and Linux, and now includes Docker support for running as a service.

## Features

- Dashboard with indoor/outdoor summary, daily charts, weekly overview, and alerts
- Multi-floor map with sensor placement, severity markers, and auto rotation
- Alarm page with active alarms, history, response notes, and guidance checklists
- Role-based user management
- CSV export and source/API integration tools
- English / Thai language switching

## Tech Stack

- Python 3
- Flask
- Waitress
- SQLite
- Bootstrap 5
- Chart.js

## Project Structure

```text
ICON_Milesight/
|-- app.py
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|-- settings.json
|-- sensordata.db
|-- calendar.db
|-- alarm.db
|-- api.db
|-- auth.db
|-- services/
|-- templates/
|-- static/
|   `-- uploads/
`-- scripts/
```

## Default Access

- Guest users can open the map page.
- Logged-in users can access pages based on role permissions.
- Default admin credentials:

```text
Username: admin
Password: admin123
```

Change the admin password after first login.

## Local Installation

### Windows (PowerShell)

Requirements:

- Python 3.11 or newer

Steps:

```powershell
git clone <your-repository-url>
cd ICON_Milesight

py -3 -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

$env:ICON_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

### Linux

Requirements:

- Python 3.11 or newer
- `python3-venv`

Steps:

```bash
git clone <your-repository-url>
cd ICON_Milesight

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

export ICON_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Docker Service

### Requirements

- Docker Engine + Docker Compose plugin

or on Windows:

- Docker Desktop

### Quick Start

1. Copy the example environment file.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux:

```bash
cp .env.example .env
```

2. Generate a real secret key and put it in `.env`.

Windows PowerShell:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Linux:

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

```env
APP_PORT=5000
ICON_SECRET_KEY=paste-generated-secret-here
ICON_DEBUG=0
```

3. Build and start the service.

```bash
docker compose up --build -d
```

4. Open the app.

```text
http://127.0.0.1:5000
```

### Docker Commands

Start:

```bash
docker compose up -d
```

Rebuild:

```bash
docker compose up --build -d
```

View logs:

```bash
docker compose logs -f
```

Stop:

```bash
docker compose down
```

### Docker Persistence

Docker Compose stores data in:

- `icon_data` named volume for SQLite databases and `settings.json`
- `./static/uploads` bind mount for uploaded images and assets

Inside the container:

- data directory: `/data`
- app directory: `/app`

## Environment Variables

The app supports these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ICON_SECRET_KEY` | `replace-with-secure-secret` | Flask session secret |
| `ICON_DATA_DIR` | project root | directory for SQLite DB files and `settings.json` |
| `ICON_SETTINGS_PATH` | `<ICON_DATA_DIR>/settings.json` | optional custom settings path |
| `ICON_SKIP_RUNTIME_BOOTSTRAP` | `0` | skip auto dependency bootstrap |
| `ICON_HOST` | `0.0.0.0` | host for `python app.py` |
| `ICON_PORT` | `5000` | port for `python app.py` |
| `ICON_DEBUG` | `1` when using `python app.py` | enable or disable debug mode |
| `APP_PORT` | `5000` | external Docker Compose port |

## How To Use The Project

1. Open the map page as guest, or log in for full access.
2. Go to `Settings` to configure:
   - project name and branding
   - floor plans
   - source/API settings
   - user roles and page permissions
3. Use the dashboard page at `/dashboard` for charts and IAQ overview.
4. Use the map page for sensor placement and monitoring.
5. Use the alarms page for active alarms, history, and response tracking.

## Data Files

The app creates and uses these SQLite files:

- `sensordata.db`
- `calendar.db`
- `alarm.db`
- `api.db`
- `auth.db`

The app also uses:

- `settings.json`
- `static/uploads/` for uploaded assets

## Milesight Ingest API

See:

- `docs_milesight_ingest_api.md`

This document describes how to send Milesight readings into the dashboard.

## Troubleshooting

### Port already in use

Change the port:

- local run: set `ICON_PORT`
- Docker: change `APP_PORT` in `.env`

### Reset local data

Delete the SQLite files and `settings.json` if you want a clean start.

### Reset Docker data

Stop the stack and remove the Docker volume:

```bash
docker compose down -v
```

## Notes

- Uploaded files are stored in `static/uploads`.
- Docker mode is the easiest way to run this project as a service.
- Local mode is best for development and template changes.
