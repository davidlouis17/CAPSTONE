from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator, Optional

from app.config import DATABASE_PATH


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Buat koneksi SQLite dengan Row factory dan foreign keys aktif."""
    target = db_path or DATABASE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admins (
    admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'management')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    criteria_weights TEXT NOT NULL,
    grade_thresholds TEXT NOT NULL,
    discount_percentage TEXT NOT NULL,
    rounding_unit INTEGER NOT NULL DEFAULT 5000,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shoes (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    brand VARCHAR(100) NOT NULL,
    model_name VARCHAR(120) NOT NULL DEFAULT '',
    size_eu VARCHAR(20) NOT NULL DEFAULT '',
    usage_duration VARCHAR(50) NOT NULL,
    purchase_price REAL NOT NULL CHECK (purchase_price >= 0),
    reference_new_price REAL NOT NULL CHECK (reference_new_price > 0),
    originality_status VARCHAR(50) NOT NULL,
    physical_verified INTEGER NOT NULL DEFAULT 0,
    verification_notes TEXT NOT NULL DEFAULT '',
    process_status VARCHAR(50) NOT NULL DEFAULT 'draft'
        CHECK (process_status IN ('draft', 'pending_review', 'approved', 'rejected', 'published', 'ml_failed')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);

CREATE TABLE IF NOT EXISTS shoe_photos (
    photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    angle_type VARCHAR(20) NOT NULL CHECK (angle_type IN ('top', 'right', 'left', 'bottom')),
    file_path VARCHAR(255) NOT NULL,
    is_valid INTEGER NOT NULL DEFAULT 1,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, angle_type),
    FOREIGN KEY (product_id) REFERENCES shoes(product_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    condition_score REAL NOT NULL,
    condition_label VARCHAR(50) NOT NULL DEFAULT '',
    criteria_breakdown TEXT NOT NULL DEFAULT '{}',
    total_points REAL NOT NULL,
    assigned_grade VARCHAR(10) NOT NULL CHECK (assigned_grade IN ('A', 'B', 'C', 'D')),
    recommended_price REAL NOT NULL CHECK (recommended_price >= 0),
    final_grade VARCHAR(10) NOT NULL CHECK (final_grade IN ('A', 'B', 'C', 'D')),
    final_price REAL NOT NULL CHECK (final_price >= 0),
    rule_version INTEGER NOT NULL,
    model_version VARCHAR(50) NOT NULL DEFAULT 'cnn-visual-v1',
    status VARCHAR(30) NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES shoes(product_id) ON DELETE CASCADE,
    FOREIGN KEY (rule_version) REFERENCES system_rules(version)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    admin_id INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    correction_reason TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES shoes(product_id) ON DELETE SET NULL,
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
);

CREATE INDEX IF NOT EXISTS idx_shoes_status ON shoes(process_status);
CREATE INDEX IF NOT EXISTS idx_shoe_photos_product ON shoe_photos(product_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_product ON evaluations(product_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_product ON audit_logs(product_id);
"""


def init_db(db_path: Optional[Path] = None) -> None:
    """Inisialisasi seluruh tabel basis data sesuai SDD Bagian 5."""
    with db_session(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
