from pathlib import Path
from app.database import db_session, init_db
from app.security import hash_password, verify_password
from app.seed import seed_database


def test_password_hashing():
    hashed = hash_password("rahasia123")
    assert hashed != "rahasia123"
    assert verify_password("rahasia123", hashed) is True
    assert verify_password("salah", hashed) is False


def test_schema_and_idempotent_seed(tmp_path: Path):
    test_db = tmp_path / "test_local_thrift.db"
    init_db(test_db)

    first = seed_database(test_db)
    assert first["admins"] == 2
    assert first["rules"] == 1
    assert first["shoes"] == 4

    second = seed_database(test_db)
    assert second == {"admins": 0, "rules": 0, "shoes": 0}

    with db_session(test_db) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {"admins", "system_rules", "shoes", "shoe_photos", "evaluations", "audit_logs"}
        assert expected.issubset(tables)

        # Pastikan setiap sepatu punya tepat 4 foto sudut (BR-002)
        photo_counts = conn.execute(
            "SELECT product_id, COUNT(*) AS cnt FROM shoe_photos GROUP BY product_id"
        ).fetchall()
        assert len(photo_counts) == 4
        assert all(row["cnt"] == 4 for row in photo_counts)

        # Pastikan Grade D tidak lolos query katalog publik (BR-009)
        public_rows = conn.execute(
            """
            SELECT s.brand, e.final_grade
            FROM shoes s
            JOIN evaluations e ON e.product_id = s.product_id
            WHERE s.process_status = 'published' AND e.final_grade != 'D'
            """
        ).fetchall()
        assert len(public_rows) == 2
        assert all(row["final_grade"] != "D" for row in public_rows)
