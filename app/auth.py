from typing import Optional
from fastapi import Request

from app.database import db_session
from app.security import verify_password


def authenticate_admin(email: str, password: str) -> Optional[dict]:
    """Verifikasi kredensial admin terhadap password_hash di database (FR-001, NFR-001)."""
    cleaned_email = email.strip().lower()
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT admin_id, name, email, password_hash, role, is_active
            FROM admins
            WHERE LOWER(email) = ?
            """,
            (cleaned_email,),
        ).fetchone()
    if not row or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {
        "admin_id": row["admin_id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
    }


def get_current_admin(request: Request) -> Optional[dict]:
    """Ambil data admin aktif dari session cookie di sisi server (NFR-002)."""
    admin_id = request.session.get("admin_id")
    if not admin_id:
        return None
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT admin_id, name, email, role, is_active
            FROM admins
            WHERE admin_id = ? AND is_active = 1
            """,
            (admin_id,),
        ).fetchone()
    if not row:
        request.session.clear()
        return None
    return dict(row)
