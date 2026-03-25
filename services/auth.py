from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from services.db import AUTH_DB, connect


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_role(role):
    normalized = str(role or "").strip().lower()
    normalized = "".join(character for character in normalized if character.isalnum() or character in {"_", "-"})
    return normalized or "user"


def ensure_default_admin_user(settings):
    username = str(settings.get("admin_username") or "admin").strip() or "admin"
    password = str(settings.get("admin_password") or "admin123")
    full_name = str(settings.get("project_name") or "Administrator").strip() or "Administrator"
    with connect(AUTH_DB) as conn:
        existing = conn.execute(
            "SELECT id, password_hash FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        now = _utc_now()
        if not existing:
            conn.execute(
                """
                INSERT INTO users (username, full_name, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', 1, ?, ?)
                """,
                (username, full_name, generate_password_hash(password), now, now),
            )
        elif not check_password_hash(existing["password_hash"], password):
            conn.execute(
                "UPDATE users SET username = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                (username, generate_password_hash(password), now, existing["id"]),
            )


def list_users():
    with connect(AUTH_DB) as conn:
        return conn.execute(
            """
            SELECT id, username, full_name, role, is_active, created_at, updated_at, last_login_at
            FROM users
            ORDER BY lower(username)
            """
        ).fetchall()


def list_login_history(limit=10, start_date="", end_date=""):
    clauses = []
    params = []
    start_date_text = str(start_date or "").strip()
    end_date_text = str(end_date or "").strip()
    if start_date_text:
        clauses.append("date(ts) >= date(?)")
        params.append(start_date_text)
    if end_date_text:
        clauses.append("date(ts) <= date(?)")
        params.append(end_date_text)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(int(limit))
    with connect(AUTH_DB) as conn:
        return conn.execute(
            f"""
            SELECT id, ts, user_id, username, attempted_username, success, ip_address,
                   location_text, request_method, request_path, user_agent, session_id
            FROM login_history
            {where_sql}
            ORDER BY ts DESC, id DESC
            {limit_sql}
            """,
            tuple(params),
        ).fetchall()


def create_user(username, password, full_name="", role="admin", is_active=True):
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("Username is required")
    if not str(password or "").strip():
        raise ValueError("Password is required")
    now = _utc_now()
    with connect(AUTH_DB) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?)",
            (normalized_username,),
        ).fetchone()
        if existing:
            raise ValueError("Username already exists")
        conn.execute(
            """
            INSERT INTO users (username, full_name, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_username,
                str(full_name or "").strip() or None,
                generate_password_hash(password),
                normalize_role(role),
                1 if is_active else 0,
                now,
                now,
            ),
        )


def update_user_role(user_id, role):
    normalized_role = normalize_role(role)
    now = _utc_now()
    with connect(AUTH_DB) as conn:
        user = conn.execute("SELECT id, role FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not user:
            raise ValueError("User not found")
        if user["role"] == "admin" and normalized_role != "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE is_active = 1 AND role = 'admin'"
            ).fetchone()["total"]
            if admin_count <= 1:
                raise ValueError("At least one active admin user is required")
        conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (normalized_role, now, int(user_id)),
        )


def update_user_password(user_id, password):
    if not str(password or "").strip():
        raise ValueError("Password is required")
    now = _utc_now()
    with connect(AUTH_DB) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (generate_password_hash(password), now, int(user_id)),
        )


def delete_user(user_id):
    with connect(AUTH_DB) as conn:
        user = conn.execute("SELECT id, username, role FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not user:
            return
        if user["role"] == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE is_active = 1 AND role = 'admin'"
            ).fetchone()["total"]
            if admin_count <= 1 and user["username"]:
                raise ValueError("At least one active admin user is required")
        conn.execute("DELETE FROM users WHERE id = ?", (int(user_id),))


def authenticate_user(username, password):
    normalized_username = str(username or "").strip()
    with connect(AUTH_DB) as conn:
        user = conn.execute(
            """
            SELECT id, username, full_name, password_hash, role, is_active
            FROM users
            WHERE lower(username) = lower(?)
            """,
            (normalized_username,),
        ).fetchone()
        if not user or not user["is_active"]:
            return None
        if not check_password_hash(user["password_hash"], str(password or "")):
            return None
        now = _utc_now()
        conn.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user["id"]),
        )
        return user


def log_login_attempt(
    *,
    attempted_username="",
    user=None,
    success=False,
    ip_address="",
    location_text="",
    request_method="",
    request_path="",
    user_agent="",
    session_id="",
):
    with connect(AUTH_DB) as conn:
        conn.execute(
            """
            INSERT INTO login_history (
                ts, user_id, username, attempted_username, success, ip_address, location_text,
                request_method, request_path, user_agent, session_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                user["id"] if user else None,
                user["username"] if user else None,
                str(attempted_username or "").strip() or None,
                1 if success else 0,
                str(ip_address or "").strip() or None,
                str(location_text or "").strip() or None,
                str(request_method or "").strip() or None,
                str(request_path or "").strip() or None,
                str(user_agent or "").strip() or None,
                str(session_id or "").strip() or None,
            ),
        )
