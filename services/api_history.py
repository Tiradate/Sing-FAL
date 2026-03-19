import json
import json
from datetime import datetime, timezone

from services.db import API_DB, connect


def _json_text(value):
    if value in (None, ""):
        return ""
    return json.dumps(value, ensure_ascii=True)


def log_api_request_history(entry):
    payload = dict(entry or {})
    with connect(API_DB) as conn:
        cursor = conn.execute(
            """
            INSERT INTO api_request_history (
                created_at,
                source_name,
                request_role,
                request_name,
                request_method,
                request_path,
                request_url,
                use_auth,
                request_headers,
                request_query,
                request_body,
                response_status,
                response_code,
                response_payload,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
                str(payload.get("source_name") or "").strip(),
                str(payload.get("request_role") or "").strip(),
                str(payload.get("request_name") or "").strip(),
                str(payload.get("request_method") or "").strip(),
                str(payload.get("request_path") or "").strip(),
                str(payload.get("request_url") or "").strip(),
                1 if payload.get("use_auth", True) else 0,
                _json_text(payload.get("request_headers")),
                _json_text(payload.get("request_query")),
                str(payload.get("request_body") or ""),
                str(payload.get("response_status") or "").strip(),
                payload.get("response_code"),
                _json_text(payload.get("response_payload")),
                str(payload.get("error_message") or "").strip(),
            ),
        )
        return cursor.lastrowid


def _history_filters(filters=None):
    filters = dict(filters or {})
    clauses = []
    params = []

    for key, column in (
        ("source_name", "source_name"),
        ("request_role", "request_role"),
        ("request_name", "request_name"),
        ("request_method", "request_method"),
        ("request_path", "request_path"),
    ):
        value = str(filters.get(key) or "").strip()
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    created_from = str(filters.get("created_from") or "").strip()
    if created_from:
        clauses.append("created_at >= ?")
        params.append(created_from)
    created_to = str(filters.get("created_to") or "").strip()
    if created_to:
        clauses.append("created_at < ?")
        params.append(created_to)
    return clauses, params


def list_api_request_history(filters=None, limit=20):
    clauses, params = _history_filters(filters)

    query = """
        SELECT
            id,
            created_at,
            source_name,
            request_role,
            request_name,
            request_method,
            request_path,
            request_url,
            use_auth,
            request_headers,
            request_query,
            request_body,
            response_status,
            response_code,
            response_payload,
            error_message
        FROM api_request_history
    """
    if clauses:
        query += f" WHERE {' AND '.join(clauses)}"
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 20), 5000)))

    with connect(API_DB) as conn:
        rows = conn.execute(query, params).fetchall()

    results = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "source_name": row["source_name"] or "",
                "request_role": row["request_role"] or "",
                "request_name": row["request_name"] or "",
                "request_method": row["request_method"] or "",
                "request_path": row["request_path"] or "",
                "request_url": row["request_url"] or "",
                "use_auth": bool(row["use_auth"]),
                "request_headers": _parse_json_text(row["request_headers"]),
                "request_query": _parse_json_text(row["request_query"]),
                "request_body": row["request_body"] or "",
                "response_status": row["response_status"] or "",
                "response_code": row["response_code"],
                "response_payload": _parse_json_text(row["response_payload"]),
                "error_message": row["error_message"] or "",
            }
        )
    return results


def export_api_request_history(filters=None, limit=50000):
    clauses, params = _history_filters(filters)

    query = """
        SELECT
            id,
            created_at,
            source_name,
            request_role,
            request_name,
            request_method,
            request_path,
            request_url,
            use_auth,
            request_headers,
            request_query,
            request_body,
            response_status,
            response_code,
            response_payload,
            error_message
        FROM api_request_history
    """
    if clauses:
        query += f" WHERE {' AND '.join(clauses)}"
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 50000), 50000)))

    with connect(API_DB) as conn:
        rows = conn.execute(query, params).fetchall()

    results = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "created_at": row["created_at"] or "",
                "source_name": row["source_name"] or "",
                "request_role": row["request_role"] or "",
                "request_name": row["request_name"] or "",
                "request_method": row["request_method"] or "",
                "request_path": row["request_path"] or "",
                "request_url": row["request_url"] or "",
                "use_auth": bool(row["use_auth"]),
                "request_headers": _parse_json_text(row["request_headers"]),
                "request_query": _parse_json_text(row["request_query"]),
                "request_body": row["request_body"] or "",
                "response_status": row["response_status"] or "",
                "response_code": row["response_code"],
                "response_payload": _parse_json_text(row["response_payload"]),
                "error_message": row["error_message"] or "",
            }
        )
    return results


def delete_api_request_history(history_id):
    with connect(API_DB) as conn:
        cursor = conn.execute(
            "DELETE FROM api_request_history WHERE id = ?",
            (int(history_id),),
        )
        return cursor.rowcount > 0


def latest_api_request_history(filters=None):
    results = list_api_request_history(filters=filters, limit=1)
    return results[0] if results else None


def _parse_json_text(value):
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
