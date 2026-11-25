from collections import defaultdict
from threading import Lock
import time
from typing import Optional
from fastapi import Request

from app.database import db_session
from app.security import verify_password

MAX_LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 menit

_attempt_lock = Lock()
_failed_attempts: dict[str, list[float]] = defaultdict(list)


def _rate_key(client_ip: str, email: str) -> str:
    return f"{client_ip.strip()}|{email.strip().lower()}"


def check_login_rate_limit(client_ip: str, email: str) -> tuple[bool, int]:
    """Periksa apakah percobaan login sedang dibatasi (rate limit brute-force).
    Mengembalikan (is_blocked, retry_after_seconds).
    """
    now = time.monotonic()
    key = _rate_key(client_ip, email)
    with _attempt_lock:
        recent = [ts for ts in _failed_attempts[key] if now - ts < WINDOW_SECONDS]
        _failed_attempts[key] = recent
        if len(recent) >= MAX_LOGIN_ATTEMPTS:
            retry_after = max(1, int(WINDOW_SECONDS - (now - recent[0])))
            return True, retry_after
    return False, 0


def record_failed_login(client_ip: str, email: str) -> int:
    """Catat kegagalan login dan kembalikan sisa kesempatan sebelum dikunci."""
    now = time.monotonic()
    key = _rate_key(client_ip, email)
    with _attempt_lock:
        recent = [ts for ts in _failed_attempts[key] if now - ts < WINDOW_SECONDS]
        recent.append(now)
        _failed_attempts[key] = recent
        return max(0, MAX_LOGIN_ATTEMPTS - len(recent))


def clear_failed_logins(client_ip: str, email: str) -> None:
    key = _rate_key(client_ip, email)
    with _attempt_lock:
        _failed_attempts.pop(key, None)


def reset_all_login_attempts() -> None:
    """Helper untuk pengujian otomatis agar state rate limiter bersih."""
    with _attempt_lock:
        _failed_attempts.clear()


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
