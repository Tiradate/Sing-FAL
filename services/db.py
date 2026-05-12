import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.environ.get("ICON_DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

SENSOR_DB = os.path.join(DATA_DIR, "sensordata.db")
CALENDAR_DB = os.path.join(DATA_DIR, "calendar.db")
ALARM_DB = os.path.join(DATA_DIR, "alarm.db")
API_DB = os.path.join(DATA_DIR, "api.db")
AUTH_DB = os.path.join(DATA_DIR, "auth.db")
ACCOUNTING_DB = os.path.join(DATA_DIR, "accounting.db")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_sensor_db():
    with connect(SENSOR_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                model TEXT,
                floor_id TEXT,
                zone TEXT,
                label TEXT,
                sensor_types TEXT,
                location_x REAL,
                location_y REAL,
                sensor_icon TEXT,
                last_seen DATETIME,
                signal_quality INTEGER,
                source_name TEXT,
                source_device_name TEXT,
                source_device_uuid TEXT
            );
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME,
                ingested_at DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                raw_value TEXT,
                unit TEXT,
                topic TEXT DEFAULT 'Live'
            );
            CREATE TABLE IF NOT EXISTS alarm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                active INTEGER DEFAULT 1
            );
            """
        )
        device_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()
        }
        if "label" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN label TEXT")
        if "sensor_types" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN sensor_types TEXT")
        if "sensor_icon" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN sensor_icon TEXT")
        if "source_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_name TEXT")
        if "source_device_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_device_name TEXT")
        if "source_device_uuid" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_device_uuid TEXT")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sensor_readings)").fetchall()}
        if "ingested_at" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN ingested_at DATETIME")
        if "topic" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN topic TEXT DEFAULT 'Live'")
        if "raw_value" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN raw_value TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sensor_ts ON sensor_readings (ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sensor_device_ts ON sensor_readings (device_id, ts)"
        )


def init_calendar_db():
    with connect(CALENDAR_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_alarm_summary (
                date DATE PRIMARY KEY,
                total_alarm INTEGER,
                moderate_count INTEGER,
                unhealthy_count INTEGER
            );
            """
        )


def init_alarm_db():
    with connect(ALARM_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS alarm_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alarm_event_id INTEGER,
                ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                action_owner TEXT,
                action_note TEXT
            );
            CREATE TABLE IF NOT EXISTS action_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alarm_event_id INTEGER,
                action_ts DATETIME,
                alarm_ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                action_owner TEXT,
                action_note TEXT,
                checklist TEXT
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(alarm_history)").fetchall()}
        if "alarm_event_id" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN alarm_event_id INTEGER")
        if "action_owner" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN action_owner TEXT")
        if "action_note" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN action_note TEXT")
        action_columns = {row["name"] for row in conn.execute("PRAGMA table_info(action_history)").fetchall()}
        if "alarm_event_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN alarm_event_id INTEGER")
        if "action_ts" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_ts DATETIME")
        if "alarm_ts" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN alarm_ts DATETIME")
        if "device_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN device_id TEXT")
        if "floor_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN floor_id TEXT")
        if "metric" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN metric TEXT")
        if "value" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN value REAL")
        if "severity" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN severity TEXT")
        if "message" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN message TEXT")
        if "action_owner" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_owner TEXT")
        if "action_note" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_note TEXT")
        if "checklist" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN checklist TEXT")


def init_api_db():
    with connect(API_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS api_request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME NOT NULL,
                source_name TEXT,
                request_role TEXT,
                request_name TEXT,
                request_method TEXT,
                request_path TEXT,
                request_url TEXT,
                use_auth INTEGER DEFAULT 1,
                request_headers TEXT,
                request_query TEXT,
                request_body TEXT,
                response_status TEXT,
                response_code INTEGER,
                response_payload TEXT,
                error_message TEXT
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(api_request_history)").fetchall()
        }
        if "response_code" not in columns:
            conn.execute("ALTER TABLE api_request_history ADD COLUMN response_code INTEGER")


def init_auth_db():
    with connect(AUTH_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_login_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME NOT NULL,
                user_id INTEGER,
                username TEXT,
                attempted_username TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                ip_address TEXT,
                location_text TEXT,
                request_method TEXT,
                request_path TEXT,
                user_agent TEXT,
                session_id TEXT
            );
            """
        )
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "full_name" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        if "role" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        if "is_active" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "last_login_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(login_history)").fetchall()}
        if "location_text" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN location_text TEXT")
        if "request_method" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN request_method TEXT")
        if "request_path" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN request_path TEXT")
        if "user_agent" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN user_agent TEXT")
        if "session_id" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN session_id TEXT")
        conn.execute("UPDATE users SET role = 'guest' WHERE role = 'user'")


def init_accounting_db():
    with connect(ACCOUNTING_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                account_type TEXT,
                parent_id INTEGER,
                is_group INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                description TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL UNIQUE,
                invoice_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                issue_date DATE NOT NULL,
                due_date DATE,
                counterparty_name TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'THB',
                notes TEXT,
                settlement_account_id INTEGER NOT NULL,
                tax_account_id INTEGER,
                subtotal REAL NOT NULL DEFAULT 0,
                tax_rate REAL NOT NULL DEFAULT 0,
                tax_amount REAL NOT NULL DEFAULT 0,
                total_amount REAL NOT NULL DEFAULT 0,
                posted_entry_id INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                description TEXT,
                account_id INTEGER NOT NULL,
                qty REAL NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                amount REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_number TEXT NOT NULL UNIQUE,
                entry_date DATE NOT NULL,
                memo TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                reference_type TEXT,
                reference_id INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                description TEXT,
                debit REAL NOT NULL DEFAULT 0,
                credit REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS payment_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_number TEXT NOT NULL UNIQUE,
                payment_date DATE NOT NULL,
                invoice_id INTEGER NOT NULL,
                payment_account_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                memo TEXT,
                posted_entry_id INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            """
        )
        account_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()
        }
        if "account_type" not in account_columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN account_type TEXT")
        if "parent_id" not in account_columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN parent_id INTEGER")
        if "is_group" not in account_columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN is_group INTEGER NOT NULL DEFAULT 0")
        if "is_active" not in account_columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "description" not in account_columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN description TEXT")

        invoice_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()
        }
        if "currency" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN currency TEXT NOT NULL DEFAULT 'THB'")
        if "notes" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN notes TEXT")
        if "settlement_account_id" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN settlement_account_id INTEGER")
        if "tax_account_id" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN tax_account_id INTEGER")
        if "subtotal" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN subtotal REAL NOT NULL DEFAULT 0")
        if "tax_rate" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN tax_rate REAL NOT NULL DEFAULT 0")
        if "tax_amount" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN tax_amount REAL NOT NULL DEFAULT 0")
        if "total_amount" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN total_amount REAL NOT NULL DEFAULT 0")
        if "posted_entry_id" not in invoice_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN posted_entry_id INTEGER")

        journal_entry_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)").fetchall()
        }
        if "reference_type" not in journal_entry_columns:
            conn.execute("ALTER TABLE journal_entries ADD COLUMN reference_type TEXT")
        if "reference_id" not in journal_entry_columns:
            conn.execute("ALTER TABLE journal_entries ADD COLUMN reference_id INTEGER")

        payment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(payment_entries)").fetchall()
        }
        if "memo" not in payment_columns:
            conn.execute("ALTER TABLE payment_entries ADD COLUMN memo TEXT")
        if "posted_entry_id" not in payment_columns:
            conn.execute("ALTER TABLE payment_entries ADD COLUMN posted_entry_id INTEGER")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounting_accounts_code ON accounts (code)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accounting_invoices_issue_date ON invoices (issue_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accounting_journal_entries_date ON journal_entries (entry_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accounting_journal_lines_account ON journal_lines (account_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accounting_payment_entries_date ON payment_entries (payment_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accounting_payment_entries_invoice ON payment_entries (invoice_id)"
        )

        existing_accounts = conn.execute("SELECT COUNT(*) AS total FROM accounts").fetchone()
        if int(existing_accounts["total"] or 0) == 0:
            now = datetime.now(timezone.utc).isoformat()
            default_accounts = [
                ("1000", "Cash on Hand", "asset", "cash", 0, 1, "Default cash account"),
                ("1100", "Accounts Receivable", "asset", "receivable", 0, 1, "Default customer receivable account"),
                ("1200", "VAT Input", "asset", "tax", 0, 1, "Input tax receivable"),
                ("2000", "Accounts Payable", "liability", "payable", 0, 1, "Default supplier payable account"),
                ("2100", "VAT Output", "liability", "tax", 0, 1, "Output tax payable"),
                ("3000", "Owner Equity", "equity", "equity", 0, 1, "Owner equity / retained earnings"),
                ("4000", "Sales Revenue", "income", "revenue", 0, 1, "Default sales income account"),
                ("4100", "Service Revenue", "income", "revenue", 0, 1, "Default service income account"),
                ("5000", "Cost of Goods Sold", "expense", "cost", 0, 1, "Cost of sales account"),
                ("6100", "Operating Expenses", "expense", "expense", 0, 1, "General operating expense account"),
            ]
            conn.executemany(
                """
                INSERT INTO accounts (
                    code,
                    name,
                    category,
                    account_type,
                    is_group,
                    is_active,
                    description,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        code,
                        name,
                        category,
                        account_type,
                        is_group,
                        is_active,
                        description,
                        now,
                        now,
                    )
                    for code, name, category, account_type, is_group, is_active, description in default_accounts
                ],
            )
def init_all():
    init_sensor_db()
    init_calendar_db()
    init_alarm_db()
    init_api_db()
    init_auth_db()
    init_accounting_db()


def seed_demo_data():
    with connect(CALENDAR_DB) as conn:
        today = datetime.now(timezone.utc).date().isoformat()
        existing = conn.execute(
            "SELECT date FROM daily_alarm_summary WHERE date = ?", (today,)
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO daily_alarm_summary (date, total_alarm, moderate_count, unhealthy_count)
                VALUES (?, ?, ?, ?)
                """,
                (today, 5, 3, 2),
            )
