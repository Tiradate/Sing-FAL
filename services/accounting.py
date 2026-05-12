from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from services.db import ACCOUNTING_DB, connect


ACCOUNT_CATEGORIES = ("asset", "liability", "equity", "income", "expense")
INVOICE_TYPES = ("sales", "purchase")
INVOICE_STATUSES = ("draft", "issued", "partially_paid", "paid", "cancelled")
JOURNAL_STATUSES = ("draft", "posted")
PAYMENT_STATUSES = ("draft", "posted")
LOCKED_REFERENCE_TYPES = {"invoice", "payment"}


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value, default=""):
    return str(value if value is not None else default).strip()


def _normalize_optional_text(value):
    text = _normalize_text(value)
    return text or None


def _to_decimal(value, default="0"):
    candidate = default if value in (None, "") else value
    try:
        return Decimal(str(candidate))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(str(default))


def _money(value):
    return float(_to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_iso_date(value, default=None):
    candidate = _normalize_text(value)
    if not candidate:
        if default is not None:
            return default
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError as exc:
        raise ValueError("Invalid date format. Use YYYY-MM-DD.") from exc


def _iso_to_date(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value)).date()


def _natural_side(category):
    return "debit" if category in {"asset", "expense"} else "credit"


def _row_value(row, key, default=None):
    return row[key] if row is not None and key in row.keys() else default


def _generate_document_number_locked(conn, prefix, table_name, column_name):
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = f"{prefix}-{date_stamp}-%"
    row = conn.execute(
        f"""
        SELECT {column_name} AS document_number
        FROM {table_name}
        WHERE {column_name} LIKE ?
        ORDER BY {column_name} DESC
        LIMIT 1
        """,
        (pattern,),
    ).fetchone()
    next_number = 1
    if row and row["document_number"]:
        try:
            next_number = int(str(row["document_number"]).rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            next_number = 1
    return f"{prefix}-{date_stamp}-{next_number:04d}"


def _get_account_row_locked(conn, account_id):
    row = conn.execute(
        """
        SELECT id, code, name, category, account_type, parent_id, is_group, is_active, description
        FROM accounts
        WHERE id = ?
        """,
        (int(account_id),),
    ).fetchone()
    if not row:
        raise ValueError("Account not found")
    return row


def _serialize_account(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "category": row["category"],
        "account_type": row["account_type"] or "",
        "parent_id": row["parent_id"],
        "is_group": bool(row["is_group"]),
        "is_active": bool(row["is_active"]),
        "description": row["description"] or "",
        "natural_side": _natural_side(row["category"]),
    }


def list_accounts(include_inactive=False):
    query = """
        SELECT id, code, name, category, account_type, parent_id, is_group, is_active, description
        FROM accounts
    """
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY code, name"
    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(query).fetchall()
    return [_serialize_account(row) for row in rows]


def get_account(account_id):
    with connect(ACCOUNTING_DB) as conn:
        return _serialize_account(_get_account_row_locked(conn, account_id))


def list_accounts_by_category(categories, include_inactive=False):
    category_list = [category for category in categories if category in ACCOUNT_CATEGORIES]
    if not category_list:
        return []
    placeholders = ", ".join("?" for _ in category_list)
    query = f"""
        SELECT id, code, name, category, account_type, parent_id, is_group, is_active, description
        FROM accounts
        WHERE category IN ({placeholders})
    """
    params = list(category_list)
    if not include_inactive:
        query += " AND is_active = 1"
    query += " ORDER BY code, name"
    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_serialize_account(row) for row in rows]


def create_account(
    code,
    name,
    category,
    account_type="",
    description="",
    parent_id=None,
    is_group=False,
    is_active=True,
):
    normalized_code = _normalize_text(code)
    normalized_name = _normalize_text(name)
    normalized_category = _normalize_text(category).lower()
    normalized_account_type = _normalize_text(account_type)
    normalized_description = _normalize_text(description)

    if not normalized_code:
        raise ValueError("Account code is required")
    if not normalized_name:
        raise ValueError("Account name is required")
    if normalized_category not in ACCOUNT_CATEGORIES:
        raise ValueError("Invalid account category")

    with connect(ACCOUNTING_DB) as conn:
        duplicate = conn.execute(
            "SELECT id FROM accounts WHERE LOWER(code) = LOWER(?)",
            (normalized_code,),
        ).fetchone()
        if duplicate:
            raise ValueError("Account code already exists")
        normalized_parent_id = None
        if parent_id not in (None, "", "0"):
            parent_row = _get_account_row_locked(conn, parent_id)
            normalized_parent_id = parent_row["id"]
        now = _utcnow_iso()
        cursor = conn.execute(
            """
            INSERT INTO accounts (
                code,
                name,
                category,
                account_type,
                parent_id,
                is_group,
                is_active,
                description,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_code,
                normalized_name,
                normalized_category,
                normalized_account_type,
                normalized_parent_id,
                int(bool(is_group)),
                int(bool(is_active)),
                normalized_description,
                now,
                now,
            ),
        )
    return cursor.lastrowid


def toggle_account_active(account_id):
    with connect(ACCOUNTING_DB) as conn:
        row = _get_account_row_locked(conn, account_id)
        next_value = 0 if bool(row["is_active"]) else 1
        conn.execute(
            "UPDATE accounts SET is_active = ?, updated_at = ? WHERE id = ?",
            (next_value, _utcnow_iso(), int(account_id)),
        )
    return bool(next_value)


def delete_account(account_id):
    with connect(ACCOUNTING_DB) as conn:
        row = _get_account_row_locked(conn, account_id)
        references = [
            conn.execute(
                "SELECT COUNT(*) AS total FROM invoice_items WHERE account_id = ?",
                (row["id"],),
            ).fetchone()["total"],
            conn.execute(
                "SELECT COUNT(*) AS total FROM invoices WHERE settlement_account_id = ? OR tax_account_id = ?",
                (row["id"], row["id"]),
            ).fetchone()["total"],
            conn.execute(
                "SELECT COUNT(*) AS total FROM journal_lines WHERE account_id = ?",
                (row["id"],),
            ).fetchone()["total"],
            conn.execute(
                "SELECT COUNT(*) AS total FROM payment_entries WHERE payment_account_id = ?",
                (row["id"],),
            ).fetchone()["total"],
        ]
        if any(int(total or 0) > 0 for total in references):
            raise ValueError("Cannot delete an account that already has transactions")
        conn.execute("DELETE FROM accounts WHERE id = ?", (row["id"],))


def _normalize_invoice_items(items):
    normalized_items = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        description = _normalize_text(item.get("description"))
        account_id = item.get("account_id")
        qty = _money(item.get("qty") or 1)
        unit_price = _money(item.get("unit_price") or 0)
        if account_id in (None, "", "0") and not description and not unit_price:
            continue
        if account_id in (None, "", "0"):
            raise ValueError("Each invoice line requires an account")
        if qty <= 0:
            raise ValueError("Invoice quantity must be greater than zero")
        amount = _money(_to_decimal(qty) * _to_decimal(unit_price))
        normalized_items.append(
            {
                "line_no": index,
                "description": description,
                "account_id": int(account_id),
                "qty": qty,
                "unit_price": unit_price,
                "amount": amount,
            }
        )
    if not normalized_items:
        raise ValueError("Add at least one invoice item")
    return normalized_items


def _normalize_journal_lines(lines):
    normalized_lines = []
    for index, line in enumerate(lines or [], start=1):
        if not isinstance(line, dict):
            continue
        account_id = line.get("account_id")
        description = _normalize_text(line.get("description"))
        debit = _money(line.get("debit") or 0)
        credit = _money(line.get("credit") or 0)
        if account_id in (None, "", "0") and debit == 0 and credit == 0 and not description:
            continue
        if account_id in (None, "", "0"):
            raise ValueError("Each journal line requires an account")
        if debit < 0 or credit < 0:
            raise ValueError("Debit and credit cannot be negative")
        if debit == 0 and credit == 0:
            raise ValueError("Each journal line must include a debit or credit amount")
        if debit > 0 and credit > 0:
            raise ValueError("A journal line cannot contain both debit and credit values")
        normalized_lines.append(
            {
                "line_no": index,
                "account_id": int(account_id),
                "description": description,
                "debit": debit,
                "credit": credit,
            }
        )
    if len(normalized_lines) < 2:
        raise ValueError("A journal entry needs at least two lines")
    total_debit = _money(sum(line["debit"] for line in normalized_lines))
    total_credit = _money(sum(line["credit"] for line in normalized_lines))
    if abs(total_debit - total_credit) > 0.009:
        raise ValueError("Journal entry is not balanced")
    return normalized_lines


def _load_journal_entry_locked(conn, entry_id):
    row = conn.execute(
        """
        SELECT
            journal_entries.*,
            COUNT(journal_lines.id) AS line_count,
            COALESCE(SUM(journal_lines.debit), 0) AS total_debit,
            COALESCE(SUM(journal_lines.credit), 0) AS total_credit
        FROM journal_entries
        LEFT JOIN journal_lines ON journal_lines.entry_id = journal_entries.id
        WHERE journal_entries.id = ?
        GROUP BY journal_entries.id
        """,
        (int(entry_id),),
    ).fetchone()
    if not row:
        raise ValueError("Journal entry not found")
    return row


def _load_journal_lines_locked(conn, entry_id):
    rows = conn.execute(
        """
        SELECT
            journal_lines.id,
            journal_lines.entry_id,
            journal_lines.line_no,
            journal_lines.account_id,
            journal_lines.description,
            journal_lines.debit,
            journal_lines.credit,
            accounts.code AS account_code,
            accounts.name AS account_name,
            accounts.category AS account_category
        FROM journal_lines
        JOIN accounts ON accounts.id = journal_lines.account_id
        WHERE journal_lines.entry_id = ?
        ORDER BY journal_lines.line_no, journal_lines.id
        """,
        (int(entry_id),),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "entry_id": row["entry_id"],
            "line_no": row["line_no"],
            "description": row["description"] or "",
            "debit": _money(row["debit"]),
            "credit": _money(row["credit"]),
            "account_id": row["account_id"],
            "account_code": row["account_code"],
            "account_name": row["account_name"],
            "account_category": row["account_category"],
        }
        for row in rows
    ]


def _serialize_journal_row(row):
    reference_type = _normalize_text(row["reference_type"]).lower()
    return {
        "id": row["id"],
        "entry_number": row["entry_number"],
        "entry_date": row["entry_date"],
        "memo": row["memo"] or "",
        "status": row["status"],
        "reference_type": row["reference_type"] or "",
        "reference_id": row["reference_id"],
        "line_count": int(row["line_count"] or 0),
        "total_debit": _money(row["total_debit"]),
        "total_credit": _money(row["total_credit"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "can_edit": row["status"] == "draft" and reference_type not in LOCKED_REFERENCE_TYPES and not reference_type,
        "can_post": row["status"] == "draft" and reference_type not in LOCKED_REFERENCE_TYPES and not reference_type,
        "can_delete": row["status"] == "draft" and reference_type not in LOCKED_REFERENCE_TYPES and not reference_type,
    }


def _create_journal_entry_locked(
    conn,
    entry_date,
    memo,
    lines,
    status="draft",
    reference_type=None,
    reference_id=None,
    entry_number=None,
):
    normalized_status = _normalize_text(status or "draft").lower()
    if normalized_status not in JOURNAL_STATUSES:
        normalized_status = "draft"
    normalized_entry_date = _normalize_iso_date(entry_date)
    normalized_memo = _normalize_text(memo)
    normalized_lines = _normalize_journal_lines(lines)

    for line in normalized_lines:
        account = _get_account_row_locked(conn, line["account_id"])
        if not bool(account["is_active"]):
            raise ValueError(f"Account {account['code']} is inactive")

    document_number = entry_number or _generate_document_number_locked(
        conn,
        "JE",
        "journal_entries",
        "entry_number",
    )
    now = _utcnow_iso()
    cursor = conn.execute(
        """
        INSERT INTO journal_entries (
            entry_number,
            entry_date,
            memo,
            status,
            reference_type,
            reference_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_number,
            normalized_entry_date,
            normalized_memo,
            normalized_status,
            _normalize_optional_text(reference_type),
            reference_id,
            now,
            now,
        ),
    )
    entry_id = cursor.lastrowid
    conn.executemany(
        """
        INSERT INTO journal_lines (
            entry_id,
            line_no,
            account_id,
            description,
            debit,
            credit
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                entry_id,
                line["line_no"],
                line["account_id"],
                line["description"],
                line["debit"],
                line["credit"],
            )
            for line in normalized_lines
        ],
    )
    return entry_id


def create_journal_entry(entry_date, memo, lines, status="draft"):
    with connect(ACCOUNTING_DB) as conn:
        return _create_journal_entry_locked(
            conn,
            entry_date=entry_date,
            memo=memo,
            lines=lines,
            status=status,
        )


def update_journal_entry(entry_id, entry_date, memo, lines):
    with connect(ACCOUNTING_DB) as conn:
        entry = _load_journal_entry_locked(conn, entry_id)
        if entry["status"] != "draft":
            raise ValueError("Only draft journal entries can be edited")
        if _normalize_text(entry["reference_type"]):
            raise ValueError("Linked journal entries cannot be edited directly")
        normalized_lines = _normalize_journal_lines(lines)
        for line in normalized_lines:
            account = _get_account_row_locked(conn, line["account_id"])
            if not bool(account["is_active"]):
                raise ValueError(f"Account {account['code']} is inactive")
        conn.execute(
            """
            UPDATE journal_entries
            SET entry_date = ?, memo = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                _normalize_iso_date(entry_date),
                _normalize_text(memo),
                _utcnow_iso(),
                entry["id"],
            ),
        )
        conn.execute("DELETE FROM journal_lines WHERE entry_id = ?", (entry["id"],))
        conn.executemany(
            """
            INSERT INTO journal_lines (
                entry_id,
                line_no,
                account_id,
                description,
                debit,
                credit
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    entry["id"],
                    line["line_no"],
                    line["account_id"],
                    line["description"],
                    line["debit"],
                    line["credit"],
                )
                for line in normalized_lines
            ],
        )
    return int(entry_id)


def get_journal_entry(entry_id):
    with connect(ACCOUNTING_DB) as conn:
        entry = _serialize_journal_row(_load_journal_entry_locked(conn, entry_id))
        entry["lines"] = _load_journal_lines_locked(conn, entry_id)
        return entry


def list_journal_entries(limit=150):
    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(
            """
            SELECT
                journal_entries.*,
                COUNT(journal_lines.id) AS line_count,
                COALESCE(SUM(journal_lines.debit), 0) AS total_debit,
                COALESCE(SUM(journal_lines.credit), 0) AS total_credit
            FROM journal_entries
            LEFT JOIN journal_lines ON journal_lines.entry_id = journal_entries.id
            GROUP BY journal_entries.id
            ORDER BY journal_entries.entry_date DESC, journal_entries.id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        entry_rows = [_serialize_journal_row(row) for row in rows]
        entry_ids = [entry["id"] for entry in entry_rows]
        lines_by_entry = defaultdict(list)
        if entry_ids:
            placeholders = ", ".join("?" for _ in entry_ids)
            line_rows = conn.execute(
                f"""
                SELECT
                    journal_lines.id,
                    journal_lines.entry_id,
                    journal_lines.line_no,
                    journal_lines.description,
                    journal_lines.debit,
                    journal_lines.credit,
                    accounts.id AS account_id,
                    accounts.code AS account_code,
                    accounts.name AS account_name,
                    accounts.category AS account_category
                FROM journal_lines
                JOIN accounts ON accounts.id = journal_lines.account_id
                WHERE journal_lines.entry_id IN ({placeholders})
                ORDER BY journal_lines.entry_id, journal_lines.line_no, journal_lines.id
                """,
                entry_ids,
            ).fetchall()
            for row in line_rows:
                lines_by_entry[row["entry_id"]].append(
                    {
                        "id": row["id"],
                        "line_no": row["line_no"],
                        "description": row["description"] or "",
                        "debit": _money(row["debit"]),
                        "credit": _money(row["credit"]),
                        "account_id": row["account_id"],
                        "account_code": row["account_code"],
                        "account_name": row["account_name"],
                        "account_category": row["account_category"],
                    }
                )
        for entry in entry_rows:
            entry["lines"] = lines_by_entry.get(entry["id"], [])
        return entry_rows


def delete_journal_entry(entry_id):
    with connect(ACCOUNTING_DB) as conn:
        row = _load_journal_entry_locked(conn, entry_id)
        if row["status"] == "posted":
            raise ValueError("Posted journal entries cannot be deleted directly")
        if _normalize_text(row["reference_type"]):
            raise ValueError("Linked journal entries cannot be deleted directly")
        conn.execute("DELETE FROM journal_lines WHERE entry_id = ?", (row["id"],))
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (row["id"],))


def post_journal_entry(entry_id):
    with connect(ACCOUNTING_DB) as conn:
        entry = _load_journal_entry_locked(conn, entry_id)
        if entry["status"] == "posted":
            return entry["id"]
        line_rows = conn.execute(
            """
            SELECT account_id, description, debit, credit
            FROM journal_lines
            WHERE entry_id = ?
            ORDER BY line_no, id
            """,
            (entry["id"],),
        ).fetchall()
        _normalize_journal_lines(
            [
                {
                    "account_id": row["account_id"],
                    "description": row["description"],
                    "debit": row["debit"],
                    "credit": row["credit"],
                }
                for row in line_rows
            ]
        )
        conn.execute(
            "UPDATE journal_entries SET status = 'posted', updated_at = ? WHERE id = ?",
            (_utcnow_iso(), entry["id"]),
        )
    return entry["id"]


def _load_invoice_locked(conn, invoice_id):
    row = conn.execute(
        """
        SELECT
            invoices.*,
            settlement_account.code AS settlement_account_code,
            settlement_account.name AS settlement_account_name,
            tax_account.code AS tax_account_code,
            tax_account.name AS tax_account_name,
            journal_entries.entry_number AS posted_entry_number
        FROM invoices
        LEFT JOIN accounts AS settlement_account ON settlement_account.id = invoices.settlement_account_id
        LEFT JOIN accounts AS tax_account ON tax_account.id = invoices.tax_account_id
        LEFT JOIN journal_entries ON journal_entries.id = invoices.posted_entry_id
        WHERE invoices.id = ?
        """,
        (int(invoice_id),),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found")
    return row


def _load_invoice_items_locked(conn, invoice_id):
    rows = conn.execute(
        """
        SELECT
            invoice_items.id,
            invoice_items.invoice_id,
            invoice_items.line_no,
            invoice_items.description,
            invoice_items.account_id,
            invoice_items.qty,
            invoice_items.unit_price,
            invoice_items.amount,
            accounts.code AS account_code,
            accounts.name AS account_name,
            accounts.category AS account_category
        FROM invoice_items
        JOIN accounts ON accounts.id = invoice_items.account_id
        WHERE invoice_items.invoice_id = ?
        ORDER BY invoice_items.line_no, invoice_items.id
        """,
        (int(invoice_id),),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "invoice_id": row["invoice_id"],
            "line_no": row["line_no"],
            "description": row["description"] or "",
            "account_id": row["account_id"],
            "account_code": row["account_code"],
            "account_name": row["account_name"],
            "account_category": row["account_category"],
            "qty": _money(row["qty"]),
            "unit_price": _money(row["unit_price"]),
            "amount": _money(row["amount"]),
        }
        for row in rows
    ]


def _load_payment_entry_locked(conn, payment_id):
    row = conn.execute(
        """
        SELECT
            payment_entries.*,
            invoices.invoice_number,
            invoices.invoice_type,
            invoices.status AS invoice_status,
            invoices.issue_date AS invoice_issue_date,
            invoices.due_date AS invoice_due_date,
            invoices.counterparty_name,
            invoices.total_amount AS invoice_total_amount,
            invoices.settlement_account_id,
            settlement_account.code AS settlement_account_code,
            settlement_account.name AS settlement_account_name,
            accounts.code AS payment_account_code,
            accounts.name AS payment_account_name,
            journal_entries.entry_number AS posted_entry_number
        FROM payment_entries
        JOIN invoices ON invoices.id = payment_entries.invoice_id
        JOIN accounts ON accounts.id = payment_entries.payment_account_id
        LEFT JOIN accounts AS settlement_account ON settlement_account.id = invoices.settlement_account_id
        LEFT JOIN journal_entries ON journal_entries.id = payment_entries.posted_entry_id
        WHERE payment_entries.id = ?
        """,
        (int(payment_id),),
    ).fetchone()
    if not row:
        raise ValueError("Payment entry not found")
    return row


def _get_posted_payment_total_locked(conn, invoice_id):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM payment_entries
        WHERE invoice_id = ?
          AND (status = 'posted' OR posted_entry_id IS NOT NULL)
        """,
        (int(invoice_id),),
    ).fetchone()
    return _money(row["total"] if row else 0)


def _calculate_invoice_payment_state(invoice_row, payment_total=0):
    total_amount = _money(_row_value(invoice_row, "total_amount", 0))
    stored_status = _normalize_text(_row_value(invoice_row, "status")).lower()
    is_posted = bool(_row_value(invoice_row, "posted_entry_id"))
    normalized_paid_amount = _money(max(0.0, min(_money(payment_total), total_amount)))
    legacy_paid = False

    if stored_status == "cancelled":
        normalized_status = "cancelled"
        paid_amount = 0.0
        outstanding_amount = 0.0
    elif stored_status == "draft" or not is_posted:
        normalized_status = "draft"
        paid_amount = 0.0
        outstanding_amount = total_amount
    elif normalized_paid_amount <= 0.009:
        if stored_status == "paid":
            legacy_paid = True
            normalized_status = "paid"
            paid_amount = total_amount
            outstanding_amount = 0.0
        else:
            normalized_status = "issued"
            paid_amount = 0.0
            outstanding_amount = total_amount
    elif normalized_paid_amount >= total_amount - 0.009:
        normalized_status = "paid"
        paid_amount = total_amount
        outstanding_amount = 0.0
    else:
        normalized_status = "partially_paid"
        paid_amount = normalized_paid_amount
        outstanding_amount = _money(total_amount - normalized_paid_amount)

    return {
        "status": normalized_status,
        "paid_amount": _money(paid_amount),
        "outstanding_amount": _money(outstanding_amount),
        "is_legacy_paid": legacy_paid,
        "can_record_payment": bool(
            is_posted
            and normalized_status in {"issued", "partially_paid"}
            and outstanding_amount > 0.009
        ),
    }


def _refresh_invoice_status_locked(conn, invoice_id):
    invoice = _load_invoice_locked(conn, invoice_id)
    if invoice["status"] == "cancelled" or not invoice["posted_entry_id"]:
        return _calculate_invoice_payment_state(invoice, 0)
    state = _calculate_invoice_payment_state(
        invoice,
        _get_posted_payment_total_locked(conn, invoice["id"]),
    )
    if state["status"] != invoice["status"]:
        conn.execute(
            "UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?",
            (state["status"], _utcnow_iso(), invoice["id"]),
        )
    return state


def _serialize_invoice_row(row, payment_state=None):
    state = payment_state or _calculate_invoice_payment_state(row, 0)
    return {
        "id": row["id"],
        "invoice_number": row["invoice_number"],
        "invoice_type": row["invoice_type"],
        "status": state["status"],
        "stored_status": row["status"],
        "issue_date": row["issue_date"],
        "due_date": row["due_date"] or "",
        "counterparty_name": row["counterparty_name"],
        "currency": row["currency"] or "THB",
        "notes": row["notes"] or "",
        "settlement_account_id": row["settlement_account_id"],
        "settlement_account_code": _row_value(row, "settlement_account_code", "") or "",
        "settlement_account_name": _row_value(row, "settlement_account_name", "") or "",
        "tax_account_id": row["tax_account_id"],
        "tax_account_code": _row_value(row, "tax_account_code", "") or "",
        "tax_account_name": _row_value(row, "tax_account_name", "") or "",
        "subtotal": _money(row["subtotal"]),
        "tax_rate": _money(row["tax_rate"]),
        "tax_amount": _money(row["tax_amount"]),
        "total_amount": _money(row["total_amount"]),
        "paid_amount": state["paid_amount"],
        "outstanding_amount": state["outstanding_amount"],
        "posted_entry_id": row["posted_entry_id"],
        "posted_entry_number": _row_value(row, "posted_entry_number", "") or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "is_posted": bool(row["posted_entry_id"]),
        "is_legacy_paid": state["is_legacy_paid"],
        "can_edit": row["status"] == "draft" and not row["posted_entry_id"],
        "can_delete": row["status"] == "draft" and not row["posted_entry_id"],
        "can_post": row["status"] == "draft" and not row["posted_entry_id"],
        "can_record_payment": state["can_record_payment"],
    }


def _serialize_payment_row(row, invoice_state=None):
    computed_status = "posted" if _row_value(row, "posted_entry_id") else _normalize_text(row["status"] or "draft").lower()
    if computed_status not in PAYMENT_STATUSES:
        computed_status = "draft"
    state = invoice_state or {}
    return {
        "id": row["id"],
        "payment_number": row["payment_number"],
        "payment_date": row["payment_date"],
        "invoice_id": row["invoice_id"],
        "invoice_number": _row_value(row, "invoice_number", "") or "",
        "invoice_type": _row_value(row, "invoice_type", "") or "",
        "invoice_status": state.get("status") or (_row_value(row, "invoice_status", "") or ""),
        "invoice_outstanding_amount": state.get("outstanding_amount"),
        "counterparty_name": _row_value(row, "counterparty_name", "") or "",
        "payment_account_id": row["payment_account_id"],
        "payment_account_code": _row_value(row, "payment_account_code", "") or "",
        "payment_account_name": _row_value(row, "payment_account_name", "") or "",
        "amount": _money(row["amount"]),
        "status": computed_status,
        "memo": row["memo"] or "",
        "posted_entry_id": row["posted_entry_id"],
        "posted_entry_number": _row_value(row, "posted_entry_number", "") or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "can_edit": computed_status == "draft" and not row["posted_entry_id"],
        "can_delete": computed_status == "draft" and not row["posted_entry_id"],
        "can_post": computed_status == "draft" and not row["posted_entry_id"],
    }


def _collect_invoice_details_locked(conn, rows):
    invoice_ids = [row["id"] for row in rows]
    if not invoice_ids:
        return []

    placeholders = ", ".join("?" for _ in invoice_ids)

    item_rows = conn.execute(
        f"""
        SELECT
            invoice_items.id,
            invoice_items.invoice_id,
            invoice_items.line_no,
            invoice_items.description,
            invoice_items.account_id,
            invoice_items.qty,
            invoice_items.unit_price,
            invoice_items.amount,
            accounts.code AS account_code,
            accounts.name AS account_name,
            accounts.category AS account_category
        FROM invoice_items
        JOIN accounts ON accounts.id = invoice_items.account_id
        WHERE invoice_items.invoice_id IN ({placeholders})
        ORDER BY invoice_items.invoice_id, invoice_items.line_no, invoice_items.id
        """,
        invoice_ids,
    ).fetchall()

    items_by_invoice = defaultdict(list)
    for row in item_rows:
        items_by_invoice[row["invoice_id"]].append(
            {
                "id": row["id"],
                "line_no": row["line_no"],
                "description": row["description"] or "",
                "account_id": row["account_id"],
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "account_category": row["account_category"],
                "qty": _money(row["qty"]),
                "unit_price": _money(row["unit_price"]),
                "amount": _money(row["amount"]),
            }
        )

    payment_total_rows = conn.execute(
        f"""
        SELECT invoice_id, COALESCE(SUM(amount), 0) AS total
        FROM payment_entries
        WHERE invoice_id IN ({placeholders})
          AND (status = 'posted' OR posted_entry_id IS NOT NULL)
        GROUP BY invoice_id
        """,
        invoice_ids,
    ).fetchall()
    payment_totals = {
        row["invoice_id"]: _money(row["total"])
        for row in payment_total_rows
    }

    payment_rows = conn.execute(
        f"""
        SELECT
            payment_entries.*,
            accounts.code AS payment_account_code,
            accounts.name AS payment_account_name,
            journal_entries.entry_number AS posted_entry_number
        FROM payment_entries
        JOIN accounts ON accounts.id = payment_entries.payment_account_id
        LEFT JOIN journal_entries ON journal_entries.id = payment_entries.posted_entry_id
        WHERE payment_entries.invoice_id IN ({placeholders})
        ORDER BY payment_entries.payment_date DESC, payment_entries.id DESC
        """,
        invoice_ids,
    ).fetchall()

    states_by_invoice = {}
    raw_by_invoice_id = {row["id"]: row for row in rows}
    for invoice_id, raw_row in raw_by_invoice_id.items():
        states_by_invoice[invoice_id] = _calculate_invoice_payment_state(
            raw_row,
            payment_totals.get(invoice_id, 0),
        )

    payments_by_invoice = defaultdict(list)
    for row in payment_rows:
        payments_by_invoice[row["invoice_id"]].append(
            _serialize_payment_row(
                row,
                invoice_state=states_by_invoice.get(row["invoice_id"]),
            )
        )

    invoices = []
    for row in rows:
        state = states_by_invoice[row["id"]]
        payload = _serialize_invoice_row(row, payment_state=state)
        payload["items"] = items_by_invoice.get(row["id"], [])
        payload["payments"] = payments_by_invoice.get(row["id"], [])
        invoices.append(payload)
    return invoices


def get_invoice(invoice_id):
    with connect(ACCOUNTING_DB) as conn:
        invoices = _collect_invoice_details_locked(conn, [_load_invoice_locked(conn, invoice_id)])
        return invoices[0]


def create_invoice(
    invoice_type,
    counterparty_name,
    issue_date,
    due_date,
    settlement_account_id,
    items,
    tax_rate=0,
    tax_account_id=None,
    currency="THB",
    notes="",
    status="draft",
):
    normalized_invoice_type = _normalize_text(invoice_type).lower()
    if normalized_invoice_type not in INVOICE_TYPES:
        raise ValueError("Invalid invoice type")
    normalized_counterparty = _normalize_text(counterparty_name)
    if not normalized_counterparty:
        raise ValueError("Customer / supplier name is required")
    normalized_issue_date = _normalize_iso_date(issue_date)
    normalized_due_date = _normalize_optional_text(due_date)
    if normalized_due_date:
        normalized_due_date = _normalize_iso_date(normalized_due_date)
    normalized_currency = (_normalize_text(currency) or "THB").upper()
    normalized_notes = _normalize_text(notes)
    normalized_status = _normalize_text(status or "draft").lower()
    if normalized_status not in INVOICE_STATUSES:
        normalized_status = "draft"
    if settlement_account_id in (None, "", "0"):
        raise ValueError("Settlement account is required")

    normalized_items = _normalize_invoice_items(items)
    subtotal = _money(sum(item["amount"] for item in normalized_items))
    normalized_tax_rate = _money(tax_rate or 0)
    tax_amount = _money(_to_decimal(subtotal) * _to_decimal(normalized_tax_rate) / Decimal("100"))
    total_amount = _money(_to_decimal(subtotal) + _to_decimal(tax_amount))

    with connect(ACCOUNTING_DB) as conn:
        settlement_account = _get_account_row_locked(conn, settlement_account_id)
        if not bool(settlement_account["is_active"]):
            raise ValueError("Settlement account is inactive")
        normalized_tax_account_id = None
        if tax_account_id not in (None, "", "0"):
            tax_account = _get_account_row_locked(conn, tax_account_id)
            if not bool(tax_account["is_active"]):
                raise ValueError("Tax account is inactive")
            normalized_tax_account_id = tax_account["id"]

        invoice_number = _generate_document_number_locked(
            conn,
            "SI" if normalized_invoice_type == "sales" else "PI",
            "invoices",
            "invoice_number",
        )
        now = _utcnow_iso()
        cursor = conn.execute(
            """
            INSERT INTO invoices (
                invoice_number,
                invoice_type,
                status,
                issue_date,
                due_date,
                counterparty_name,
                currency,
                notes,
                settlement_account_id,
                tax_account_id,
                subtotal,
                tax_rate,
                tax_amount,
                total_amount,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_number,
                normalized_invoice_type,
                "draft",
                normalized_issue_date,
                normalized_due_date,
                normalized_counterparty,
                normalized_currency,
                normalized_notes,
                int(settlement_account_id),
                normalized_tax_account_id,
                subtotal,
                normalized_tax_rate,
                tax_amount,
                total_amount,
                now,
                now,
            ),
        )
        invoice_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO invoice_items (
                invoice_id,
                line_no,
                description,
                account_id,
                qty,
                unit_price,
                amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    invoice_id,
                    item["line_no"],
                    item["description"],
                    item["account_id"],
                    item["qty"],
                    item["unit_price"],
                    item["amount"],
                )
                for item in normalized_items
            ],
        )
        if normalized_status != "draft":
            _post_invoice_locked(conn, invoice_id, next_status=normalized_status)
    return invoice_id


def update_invoice(
    invoice_id,
    invoice_type,
    counterparty_name,
    issue_date,
    due_date,
    settlement_account_id,
    items,
    tax_rate=0,
    tax_account_id=None,
    currency="THB",
    notes="",
):
    normalized_invoice_type = _normalize_text(invoice_type).lower()
    if normalized_invoice_type not in INVOICE_TYPES:
        raise ValueError("Invalid invoice type")
    normalized_counterparty = _normalize_text(counterparty_name)
    if not normalized_counterparty:
        raise ValueError("Customer / supplier name is required")
    normalized_issue_date = _normalize_iso_date(issue_date)
    normalized_due_date = _normalize_optional_text(due_date)
    if normalized_due_date:
        normalized_due_date = _normalize_iso_date(normalized_due_date)
    normalized_currency = (_normalize_text(currency) or "THB").upper()
    normalized_notes = _normalize_text(notes)
    normalized_items = _normalize_invoice_items(items)
    subtotal = _money(sum(item["amount"] for item in normalized_items))
    normalized_tax_rate = _money(tax_rate or 0)
    tax_amount = _money(_to_decimal(subtotal) * _to_decimal(normalized_tax_rate) / Decimal("100"))
    total_amount = _money(_to_decimal(subtotal) + _to_decimal(tax_amount))

    with connect(ACCOUNTING_DB) as conn:
        invoice = _load_invoice_locked(conn, invoice_id)
        if invoice["status"] != "draft" or invoice["posted_entry_id"]:
            raise ValueError("Only draft invoices can be edited")
        settlement_account = _get_account_row_locked(conn, settlement_account_id)
        if not bool(settlement_account["is_active"]):
            raise ValueError("Settlement account is inactive")
        normalized_tax_account_id = None
        if tax_account_id not in (None, "", "0"):
            tax_account = _get_account_row_locked(conn, tax_account_id)
            if not bool(tax_account["is_active"]):
                raise ValueError("Tax account is inactive")
            normalized_tax_account_id = tax_account["id"]

        conn.execute(
            """
            UPDATE invoices
            SET invoice_type = ?,
                issue_date = ?,
                due_date = ?,
                counterparty_name = ?,
                currency = ?,
                notes = ?,
                settlement_account_id = ?,
                tax_account_id = ?,
                subtotal = ?,
                tax_rate = ?,
                tax_amount = ?,
                total_amount = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalized_invoice_type,
                normalized_issue_date,
                normalized_due_date,
                normalized_counterparty,
                normalized_currency,
                normalized_notes,
                int(settlement_account_id),
                normalized_tax_account_id,
                subtotal,
                normalized_tax_rate,
                tax_amount,
                total_amount,
                _utcnow_iso(),
                invoice["id"],
            ),
        )
        conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice["id"],))
        conn.executemany(
            """
            INSERT INTO invoice_items (
                invoice_id,
                line_no,
                description,
                account_id,
                qty,
                unit_price,
                amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    invoice["id"],
                    item["line_no"],
                    item["description"],
                    item["account_id"],
                    item["qty"],
                    item["unit_price"],
                    item["amount"],
                )
                for item in normalized_items
            ],
        )
    return int(invoice_id)


def _build_invoice_posting_lines(invoice, items):
    lines = []
    total_amount = _money(invoice["total_amount"])
    tax_amount = _money(invoice["tax_amount"])
    settlement_account_id = invoice["settlement_account_id"]
    tax_account_id = invoice["tax_account_id"]

    if invoice["invoice_type"] == "sales":
        lines.append(
            {
                "account_id": settlement_account_id,
                "description": f"{invoice['invoice_number']} receivable",
                "debit": total_amount,
                "credit": 0,
            }
        )
        for item in items:
            lines.append(
                {
                    "account_id": item["account_id"],
                    "description": item["description"] or f"{invoice['invoice_number']} income",
                    "debit": 0,
                    "credit": item["amount"],
                }
            )
        if tax_amount > 0:
            if not tax_account_id:
                raise ValueError("Tax account is required when tax amount is greater than zero")
            lines.append(
                {
                    "account_id": tax_account_id,
                    "description": f"{invoice['invoice_number']} output tax",
                    "debit": 0,
                    "credit": tax_amount,
                }
            )
    else:
        for item in items:
            lines.append(
                {
                    "account_id": item["account_id"],
                    "description": item["description"] or f"{invoice['invoice_number']} expense",
                    "debit": item["amount"],
                    "credit": 0,
                }
            )
        if tax_amount > 0:
            if not tax_account_id:
                raise ValueError("Tax account is required when tax amount is greater than zero")
            lines.append(
                {
                    "account_id": tax_account_id,
                    "description": f"{invoice['invoice_number']} input tax",
                    "debit": tax_amount,
                    "credit": 0,
                }
            )
        lines.append(
            {
                "account_id": settlement_account_id,
                "description": f"{invoice['invoice_number']} payable",
                "debit": 0,
                "credit": total_amount,
            }
        )
    return lines


def _post_invoice_locked(conn, invoice_id, next_status="issued"):
    invoice = _load_invoice_locked(conn, invoice_id)
    if invoice["posted_entry_id"]:
        raise ValueError("Invoice is already posted")
    if invoice["status"] == "cancelled":
        raise ValueError("Cancelled invoices cannot be posted")
    items = _load_invoice_items_locked(conn, invoice_id)
    posting_lines = _build_invoice_posting_lines(invoice, items)
    entry_id = _create_journal_entry_locked(
        conn,
        entry_date=invoice["issue_date"],
        memo=f"{invoice['invoice_type'].title()} invoice {invoice['invoice_number']} - {invoice['counterparty_name']}",
        lines=posting_lines,
        status="posted",
        reference_type="invoice",
        reference_id=invoice["id"],
    )
    normalized_next_status = _normalize_text(next_status or "issued").lower()
    if normalized_next_status not in {"issued", "partially_paid", "paid"}:
        normalized_next_status = "issued"
    conn.execute(
        """
        UPDATE invoices
        SET status = ?, posted_entry_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (normalized_next_status, entry_id, _utcnow_iso(), invoice["id"]),
    )
    if normalized_next_status != "paid":
        _refresh_invoice_status_locked(conn, invoice["id"])
    return entry_id


def post_invoice(invoice_id, next_status="issued"):
    with connect(ACCOUNTING_DB) as conn:
        return _post_invoice_locked(conn, invoice_id, next_status=next_status)


def delete_invoice(invoice_id):
    with connect(ACCOUNTING_DB) as conn:
        invoice = _load_invoice_locked(conn, invoice_id)
        if invoice["posted_entry_id"]:
            raise ValueError("Posted invoices cannot be deleted")
        conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice["id"],))
        conn.execute("DELETE FROM invoices WHERE id = ?", (invoice["id"],))


def list_invoices(limit=100, only_open=False, invoice_type=None):
    normalized_invoice_type = _normalize_text(invoice_type).lower()
    query = """
        SELECT
            invoices.*,
            settlement_account.code AS settlement_account_code,
            settlement_account.name AS settlement_account_name,
            tax_account.code AS tax_account_code,
            tax_account.name AS tax_account_name,
            journal_entries.entry_number AS posted_entry_number
        FROM invoices
        LEFT JOIN accounts AS settlement_account ON settlement_account.id = invoices.settlement_account_id
        LEFT JOIN accounts AS tax_account ON tax_account.id = invoices.tax_account_id
        LEFT JOIN journal_entries ON journal_entries.id = invoices.posted_entry_id
        WHERE 1 = 1
    """
    params = []
    if normalized_invoice_type in INVOICE_TYPES:
        query += " AND invoices.invoice_type = ?"
        params.append(normalized_invoice_type)
    query += " ORDER BY invoices.issue_date DESC, invoices.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))

    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        invoices = _collect_invoice_details_locked(conn, rows)

    if only_open:
        invoices = [invoice for invoice in invoices if invoice["can_record_payment"]]
    return invoices


def list_open_invoices(invoice_type=None, limit=250):
    return list_invoices(limit=limit, only_open=True, invoice_type=invoice_type)


def _build_payment_posting_lines(payment, invoice):
    description = payment["memo"] or f"{payment['payment_number']} against {invoice['invoice_number']}"
    amount = _money(payment["amount"])
    settlement_account_id = invoice["settlement_account_id"]
    payment_account_id = payment["payment_account_id"]

    if invoice["invoice_type"] == "sales":
        return [
            {
                "account_id": payment_account_id,
                "description": description,
                "debit": amount,
                "credit": 0,
            },
            {
                "account_id": settlement_account_id,
                "description": description,
                "debit": 0,
                "credit": amount,
            },
        ]
    return [
        {
            "account_id": settlement_account_id,
            "description": description,
            "debit": amount,
            "credit": 0,
        },
        {
            "account_id": payment_account_id,
            "description": description,
            "debit": 0,
            "credit": amount,
        },
    ]


def create_payment_entry(
    invoice_id,
    payment_date,
    payment_account_id,
    amount,
    memo="",
    status="draft",
):
    if invoice_id in (None, "", "0"):
        raise ValueError("Invoice is required")
    if payment_account_id in (None, "", "0"):
        raise ValueError("Payment account is required")
    normalized_payment_date = _normalize_iso_date(payment_date)
    normalized_amount = _money(amount or 0)
    normalized_memo = _normalize_text(memo)
    normalized_status = _normalize_text(status or "draft").lower()
    if normalized_status not in PAYMENT_STATUSES:
        normalized_status = "draft"
    if normalized_amount <= 0:
        raise ValueError("Payment amount must be greater than zero")

    with connect(ACCOUNTING_DB) as conn:
        invoice = _load_invoice_locked(conn, invoice_id)
        if not invoice["posted_entry_id"] or invoice["status"] == "draft":
            raise ValueError("Only posted invoices can receive payments")
        if invoice["status"] == "cancelled":
            raise ValueError("Cancelled invoices cannot receive payments")
        invoice_state = _calculate_invoice_payment_state(
            invoice,
            _get_posted_payment_total_locked(conn, invoice["id"]),
        )
        if not invoice_state["can_record_payment"]:
            raise ValueError("This invoice is already fully settled")
        if normalized_amount > invoice_state["outstanding_amount"] + 0.009:
            raise ValueError("Payment amount exceeds the invoice outstanding balance")

        payment_account = _get_account_row_locked(conn, payment_account_id)
        if not bool(payment_account["is_active"]):
            raise ValueError("Payment account is inactive")

        payment_number = _generate_document_number_locked(
            conn,
            "PE",
            "payment_entries",
            "payment_number",
        )
        now = _utcnow_iso()
        cursor = conn.execute(
            """
            INSERT INTO payment_entries (
                payment_number,
                payment_date,
                invoice_id,
                payment_account_id,
                amount,
                status,
                memo,
                posted_entry_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payment_number,
                normalized_payment_date,
                int(invoice_id),
                int(payment_account_id),
                normalized_amount,
                "draft",
                normalized_memo,
                None,
                now,
                now,
            ),
        )
        payment_id = cursor.lastrowid
        if normalized_status == "posted":
            _post_payment_entry_locked(conn, payment_id)
    return payment_id


def update_payment_entry(payment_id, invoice_id, payment_date, payment_account_id, amount, memo=""):
    if invoice_id in (None, "", "0"):
        raise ValueError("Invoice is required")
    if payment_account_id in (None, "", "0"):
        raise ValueError("Payment account is required")
    normalized_payment_date = _normalize_iso_date(payment_date)
    normalized_amount = _money(amount or 0)
    normalized_memo = _normalize_text(memo)
    if normalized_amount <= 0:
        raise ValueError("Payment amount must be greater than zero")

    with connect(ACCOUNTING_DB) as conn:
        payment = _load_payment_entry_locked(conn, payment_id)
        if payment["posted_entry_id"] or payment["status"] == "posted":
            raise ValueError("Only draft payment entries can be edited")

        invoice = _load_invoice_locked(conn, invoice_id)
        if not invoice["posted_entry_id"] or invoice["status"] == "draft":
            raise ValueError("Only posted invoices can receive payments")
        if invoice["status"] == "cancelled":
            raise ValueError("Cancelled invoices cannot receive payments")

        current_posted_total = _get_posted_payment_total_locked(conn, invoice["id"])
        invoice_state = _calculate_invoice_payment_state(invoice, current_posted_total)
        if not invoice_state["can_record_payment"]:
            raise ValueError("This invoice is already fully settled")
        if normalized_amount > invoice_state["outstanding_amount"] + 0.009:
            raise ValueError("Payment amount exceeds the invoice outstanding balance")

        payment_account = _get_account_row_locked(conn, payment_account_id)
        if not bool(payment_account["is_active"]):
            raise ValueError("Payment account is inactive")

        conn.execute(
            """
            UPDATE payment_entries
            SET payment_date = ?,
                invoice_id = ?,
                payment_account_id = ?,
                amount = ?,
                memo = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalized_payment_date,
                int(invoice_id),
                int(payment_account_id),
                normalized_amount,
                normalized_memo,
                _utcnow_iso(),
                payment["id"],
            ),
        )
    return int(payment_id)


def _post_payment_entry_locked(conn, payment_id):
    payment = _load_payment_entry_locked(conn, payment_id)
    if payment["posted_entry_id"]:
        return payment["posted_entry_id"]
    invoice = _load_invoice_locked(conn, payment["invoice_id"])
    if not invoice["posted_entry_id"] or invoice["status"] == "draft":
        raise ValueError("Only posted invoices can receive payments")
    if invoice["status"] == "cancelled":
        raise ValueError("Cancelled invoices cannot receive payments")

    invoice_state = _calculate_invoice_payment_state(
        invoice,
        _get_posted_payment_total_locked(conn, invoice["id"]),
    )
    if payment["amount"] > invoice_state["outstanding_amount"] + 0.009:
        raise ValueError("Payment amount exceeds the invoice outstanding balance")

    _get_account_row_locked(conn, payment["payment_account_id"])
    posting_lines = _build_payment_posting_lines(payment, invoice)
    entry_id = _create_journal_entry_locked(
        conn,
        entry_date=payment["payment_date"],
        memo=f"Payment {payment['payment_number']} for {invoice['invoice_number']} - {invoice['counterparty_name']}",
        lines=posting_lines,
        status="posted",
        reference_type="payment",
        reference_id=payment["id"],
    )
    conn.execute(
        """
        UPDATE payment_entries
        SET status = 'posted', posted_entry_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (entry_id, _utcnow_iso(), payment["id"]),
    )
    _refresh_invoice_status_locked(conn, invoice["id"])
    return entry_id


def post_payment_entry(payment_id):
    with connect(ACCOUNTING_DB) as conn:
        return _post_payment_entry_locked(conn, payment_id)


def delete_payment_entry(payment_id):
    with connect(ACCOUNTING_DB) as conn:
        payment = _load_payment_entry_locked(conn, payment_id)
        if payment["posted_entry_id"] or payment["status"] == "posted":
            raise ValueError("Posted payment entries cannot be deleted")
        conn.execute("DELETE FROM payment_entries WHERE id = ?", (payment["id"],))


def get_payment_entry(payment_id):
    with connect(ACCOUNTING_DB) as conn:
        row = _load_payment_entry_locked(conn, payment_id)
        invoice = _load_invoice_locked(conn, row["invoice_id"])
        state = _calculate_invoice_payment_state(
            invoice,
            _get_posted_payment_total_locked(conn, invoice["id"]),
        )
        return _serialize_payment_row(row, invoice_state=state)


def list_payment_entries(limit=150):
    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(
            """
            SELECT
                payment_entries.*,
                invoices.invoice_number,
                invoices.invoice_type,
                invoices.status AS invoice_status,
                invoices.counterparty_name,
                invoices.total_amount AS invoice_total_amount,
                accounts.code AS payment_account_code,
                accounts.name AS payment_account_name,
                journal_entries.entry_number AS posted_entry_number
            FROM payment_entries
            JOIN invoices ON invoices.id = payment_entries.invoice_id
            JOIN accounts ON accounts.id = payment_entries.payment_account_id
            LEFT JOIN journal_entries ON journal_entries.id = payment_entries.posted_entry_id
            ORDER BY payment_entries.payment_date DESC, payment_entries.id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        invoice_ids = sorted({row["invoice_id"] for row in rows})
        states_by_invoice = {}
        if invoice_ids:
            placeholders = ", ".join("?" for _ in invoice_ids)
            invoice_rows = conn.execute(
                f"""
                SELECT
                    invoices.*,
                    journal_entries.entry_number AS posted_entry_number
                FROM invoices
                LEFT JOIN journal_entries ON journal_entries.id = invoices.posted_entry_id
                WHERE invoices.id IN ({placeholders})
                """,
                invoice_ids,
            ).fetchall()
            totals = {
                row["invoice_id"]: _money(row["total"])
                for row in conn.execute(
                    f"""
                    SELECT invoice_id, COALESCE(SUM(amount), 0) AS total
                    FROM payment_entries
                    WHERE invoice_id IN ({placeholders})
                      AND (status = 'posted' OR posted_entry_id IS NOT NULL)
                    GROUP BY invoice_id
                    """,
                    invoice_ids,
                ).fetchall()
            }
            for invoice_row in invoice_rows:
                states_by_invoice[invoice_row["id"]] = _calculate_invoice_payment_state(
                    invoice_row,
                    totals.get(invoice_row["id"], 0),
                )
        return [
            _serialize_payment_row(row, invoice_state=states_by_invoice.get(row["invoice_id"]))
            for row in rows
        ]


def _bucket_key_for_days(days_past_due):
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "days_1_30"
    if days_past_due <= 60:
        return "days_31_60"
    if days_past_due <= 90:
        return "days_61_90"
    return "days_over_90"


def _empty_aging_section():
    return {
        "rows": [],
        "totals": {
            "current": 0.0,
            "days_1_30": 0.0,
            "days_31_60": 0.0,
            "days_61_90": 0.0,
            "days_over_90": 0.0,
        },
        "total_open": 0.0,
    }


def get_ar_ap_aging(as_of_date=None):
    as_of = _normalize_iso_date(as_of_date or date.today().isoformat())
    as_of_dt = _iso_to_date(as_of)
    aging = {
        "as_of_date": as_of,
        "receivables": _empty_aging_section(),
        "payables": _empty_aging_section(),
    }

    invoices = list_invoices(limit=1000)
    for invoice in invoices:
        if not invoice["is_posted"] or invoice["outstanding_amount"] <= 0.009:
            continue
        issue_dt = _iso_to_date(invoice["issue_date"])
        if issue_dt and issue_dt > as_of_dt:
            continue
        due_dt = _iso_to_date(invoice["due_date"]) or issue_dt or as_of_dt
        days_past_due = max((as_of_dt - due_dt).days, 0)
        bucket_key = _bucket_key_for_days(days_past_due)
        row = {
            "invoice_id": invoice["id"],
            "invoice_number": invoice["invoice_number"],
            "invoice_type": invoice["invoice_type"],
            "counterparty_name": invoice["counterparty_name"],
            "issue_date": invoice["issue_date"],
            "due_date": invoice["due_date"] or invoice["issue_date"],
            "total_amount": invoice["total_amount"],
            "paid_amount": invoice["paid_amount"],
            "outstanding_amount": invoice["outstanding_amount"],
            "days_past_due": days_past_due,
            "current": 0.0,
            "days_1_30": 0.0,
            "days_31_60": 0.0,
            "days_61_90": 0.0,
            "days_over_90": 0.0,
        }
        row[bucket_key] = invoice["outstanding_amount"]

        section_key = "receivables" if invoice["invoice_type"] == "sales" else "payables"
        aging[section_key]["rows"].append(row)
        aging[section_key]["totals"][bucket_key] = _money(
            aging[section_key]["totals"][bucket_key] + invoice["outstanding_amount"]
        )
        aging[section_key]["total_open"] = _money(
            aging[section_key]["total_open"] + invoice["outstanding_amount"]
        )

    for section_key in ("receivables", "payables"):
        aging[section_key]["rows"].sort(
            key=lambda item: (item["days_past_due"], item["due_date"], item["invoice_number"]),
            reverse=True,
        )

    return aging


def _build_posted_activity(start_date=None, end_date=None, account_id=None):
    query = """
        SELECT
            journal_entries.id AS entry_id,
            journal_entries.entry_number,
            journal_entries.entry_date,
            journal_entries.memo,
            journal_entries.reference_type,
            journal_entries.reference_id,
            journal_lines.id AS line_id,
            journal_lines.line_no,
            journal_lines.description AS line_description,
            journal_lines.debit,
            journal_lines.credit,
            accounts.id AS account_id,
            accounts.code AS account_code,
            accounts.name AS account_name,
            accounts.category AS account_category
        FROM journal_lines
        JOIN journal_entries ON journal_entries.id = journal_lines.entry_id
        JOIN accounts ON accounts.id = journal_lines.account_id
        WHERE journal_entries.status = 'posted'
    """
    params = []
    if start_date:
        query += " AND journal_entries.entry_date >= ?"
        params.append(_normalize_iso_date(start_date))
    if end_date:
        query += " AND journal_entries.entry_date <= ?"
        params.append(_normalize_iso_date(end_date))
    if account_id not in (None, "", "0"):
        query += " AND accounts.id = ?"
        params.append(int(account_id))
    query += " ORDER BY journal_entries.entry_date, journal_entries.id, journal_lines.line_no, journal_lines.id"
    with connect(ACCOUNTING_DB) as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "entry_id": row["entry_id"],
            "entry_number": row["entry_number"],
            "entry_date": row["entry_date"],
            "memo": row["memo"] or "",
            "reference_type": row["reference_type"] or "",
            "reference_id": row["reference_id"],
            "line_id": row["line_id"],
            "line_no": row["line_no"],
            "line_description": row["line_description"] or "",
            "debit": _money(row["debit"]),
            "credit": _money(row["credit"]),
            "account_id": row["account_id"],
            "account_code": row["account_code"],
            "account_name": row["account_name"],
            "account_category": row["account_category"],
        }
        for row in rows
    ]


def get_accounting_summary(start_date=None, end_date=None):
    active_accounts = [account for account in list_accounts() if account["is_active"]]
    with connect(ACCOUNTING_DB) as conn:
        invoice_query = "SELECT status, invoice_type, total_amount FROM invoices WHERE 1 = 1"
        invoice_params = []
        if start_date:
            invoice_query += " AND issue_date >= ?"
            invoice_params.append(_normalize_iso_date(start_date))
        if end_date:
            invoice_query += " AND issue_date <= ?"
            invoice_params.append(_normalize_iso_date(end_date))
        invoice_rows = conn.execute(invoice_query, invoice_params).fetchall()

        journal_query = "SELECT status FROM journal_entries WHERE 1 = 1"
        journal_params = []
        if start_date:
            journal_query += " AND entry_date >= ?"
            journal_params.append(_normalize_iso_date(start_date))
        if end_date:
            journal_query += " AND entry_date <= ?"
            journal_params.append(_normalize_iso_date(end_date))
        journal_rows = conn.execute(journal_query, journal_params).fetchall()

        payment_query = "SELECT status FROM payment_entries WHERE 1 = 1"
        payment_params = []
        if start_date:
            payment_query += " AND payment_date >= ?"
            payment_params.append(_normalize_iso_date(start_date))
        if end_date:
            payment_query += " AND payment_date <= ?"
            payment_params.append(_normalize_iso_date(end_date))
        payment_rows = conn.execute(payment_query, payment_params).fetchall()

    sales_total = 0.0
    purchase_total = 0.0
    draft_invoices = 0
    for row in invoice_rows:
        if row["status"] == "draft":
            draft_invoices += 1
        if row["status"] != "draft":
            if row["invoice_type"] == "sales":
                sales_total += _money(row["total_amount"])
            elif row["invoice_type"] == "purchase":
                purchase_total += _money(row["total_amount"])

    posted_journals = sum(1 for row in journal_rows if row["status"] == "posted")
    draft_journals = sum(1 for row in journal_rows if row["status"] == "draft")
    posted_payments = sum(1 for row in payment_rows if row["status"] == "posted")
    draft_payments = sum(1 for row in payment_rows if row["status"] == "draft")
    aging = get_ar_ap_aging(as_of_date=end_date)
    return {
        "active_accounts": len(active_accounts),
        "draft_invoices": draft_invoices,
        "posted_journals": posted_journals,
        "draft_journals": draft_journals,
        "posted_payments": posted_payments,
        "draft_payments": draft_payments,
        "sales_total": _money(sales_total),
        "purchase_total": _money(purchase_total),
        "open_receivables": aging["receivables"]["total_open"],
        "open_payables": aging["payables"]["total_open"],
    }


def get_trial_balance(start_date=None, end_date=None):
    activity = _build_posted_activity(start_date=start_date, end_date=end_date)
    balances = {
        account["id"]: {
            "account_id": account["id"],
            "code": account["code"],
            "name": account["name"],
            "category": account["category"],
            "debit_total": 0.0,
            "credit_total": 0.0,
            "ending_debit": 0.0,
            "ending_credit": 0.0,
        }
        for account in list_accounts()
    }

    for row in activity:
        balance = balances.setdefault(
            row["account_id"],
            {
                "account_id": row["account_id"],
                "code": row["account_code"],
                "name": row["account_name"],
                "category": row["account_category"],
                "debit_total": 0.0,
                "credit_total": 0.0,
                "ending_debit": 0.0,
                "ending_credit": 0.0,
            },
        )
        balance["debit_total"] = _money(balance["debit_total"] + row["debit"])
        balance["credit_total"] = _money(balance["credit_total"] + row["credit"])

    rows = []
    total_debit = 0.0
    total_credit = 0.0
    for balance in sorted(balances.values(), key=lambda item: (item["code"], item["name"])):
        delta = _money(balance["debit_total"] - balance["credit_total"])
        balance["ending_debit"] = _money(delta if delta > 0 else 0)
        balance["ending_credit"] = _money(abs(delta) if delta < 0 else 0)
        total_debit = _money(total_debit + balance["ending_debit"])
        total_credit = _money(total_credit + balance["ending_credit"])
        rows.append(balance)
    return {
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }


def get_profit_and_loss(start_date=None, end_date=None):
    activity = _build_posted_activity(start_date=start_date, end_date=end_date)
    balances = defaultdict(
        lambda: {
            "account_id": None,
            "code": "",
            "name": "",
            "category": "",
            "amount": 0.0,
        }
    )
    for row in activity:
        if row["account_category"] not in {"income", "expense"}:
            continue
        bucket = balances[row["account_id"]]
        bucket["account_id"] = row["account_id"]
        bucket["code"] = row["account_code"]
        bucket["name"] = row["account_name"]
        bucket["category"] = row["account_category"]
        if row["account_category"] == "income":
            bucket["amount"] = _money(bucket["amount"] + row["credit"] - row["debit"])
        else:
            bucket["amount"] = _money(bucket["amount"] + row["debit"] - row["credit"])

    income_rows = sorted(
        [row for row in balances.values() if row["category"] == "income" and abs(row["amount"]) > 0.0001],
        key=lambda item: (item["code"], item["name"]),
    )
    expense_rows = sorted(
        [row for row in balances.values() if row["category"] == "expense" and abs(row["amount"]) > 0.0001],
        key=lambda item: (item["code"], item["name"]),
    )
    income_total = _money(sum(row["amount"] for row in income_rows))
    expense_total = _money(sum(row["amount"] for row in expense_rows))
    return {
        "income_rows": income_rows,
        "expense_rows": expense_rows,
        "income_total": income_total,
        "expense_total": expense_total,
        "net_profit": _money(income_total - expense_total),
    }


def get_balance_sheet(as_of_date=None):
    activity = _build_posted_activity(end_date=as_of_date)
    balances = defaultdict(
        lambda: {
            "account_id": None,
            "code": "",
            "name": "",
            "category": "",
            "amount": 0.0,
        }
    )
    current_earnings = 0.0
    for row in activity:
        category = row["account_category"]
        bucket = balances[row["account_id"]]
        bucket["account_id"] = row["account_id"]
        bucket["code"] = row["account_code"]
        bucket["name"] = row["account_name"]
        bucket["category"] = category
        if category == "asset":
            bucket["amount"] = _money(bucket["amount"] + row["debit"] - row["credit"])
        elif category in {"liability", "equity"}:
            bucket["amount"] = _money(bucket["amount"] + row["credit"] - row["debit"])
        elif category == "income":
            current_earnings = _money(current_earnings + row["credit"] - row["debit"])
        elif category == "expense":
            current_earnings = _money(current_earnings - row["debit"] + row["credit"])

    asset_rows = sorted(
        [row for row in balances.values() if row["category"] == "asset" and abs(row["amount"]) > 0.0001],
        key=lambda item: (item["code"], item["name"]),
    )
    liability_rows = sorted(
        [row for row in balances.values() if row["category"] == "liability" and abs(row["amount"]) > 0.0001],
        key=lambda item: (item["code"], item["name"]),
    )
    equity_rows = sorted(
        [row for row in balances.values() if row["category"] == "equity" and abs(row["amount"]) > 0.0001],
        key=lambda item: (item["code"], item["name"]),
    )
    if abs(current_earnings) > 0.0001:
        equity_rows.append(
            {
                "account_id": None,
                "code": "CYE",
                "name": "Current Earnings",
                "category": "equity",
                "amount": _money(current_earnings),
            }
        )

    total_assets = _money(sum(row["amount"] for row in asset_rows))
    total_liabilities = _money(sum(row["amount"] for row in liability_rows))
    total_equity = _money(sum(row["amount"] for row in equity_rows))
    return {
        "asset_rows": asset_rows,
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
    }


def get_general_ledger(account_id=None, start_date=None, end_date=None):
    activity = _build_posted_activity(start_date=start_date, end_date=end_date, account_id=account_id)
    selected_account = None
    if account_id not in (None, "", "0"):
        try:
            selected_account = get_account(account_id)
        except ValueError:
            selected_account = None
    running_balance = 0.0
    rows = []
    for row in activity:
        if selected_account:
            if selected_account["natural_side"] == "debit":
                running_balance = _money(running_balance + row["debit"] - row["credit"])
            else:
                running_balance = _money(running_balance + row["credit"] - row["debit"])
        rows.append(
            {
                **row,
                "running_balance": running_balance if selected_account else None,
            }
        )
    return {
        "selected_account": selected_account,
        "rows": rows,
    }
