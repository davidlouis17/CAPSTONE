"""Hubungkan 16 foto sampel 4 sisi (produk #1 s.d. #4) ke database local_thrift.db.

Jalankan dari root folder proyek:
    python scripts/apply_sample_photos.py
"""
from app.database import db_session


def apply_sample_photos():
    updated = 0
    with db_session() as conn:
        for product_id in (1, 2, 3, 4):
            exists = conn.execute(
                "SELECT product_id FROM shoes WHERE product_id = ?", (product_id,)
            ).fetchone()
            if not exists:
                continue
            for angle in ("top", "right", "left", "bottom"):
                file_url = f"/static/uploads/shoe_{product_id}/{angle}.jpg"
                conn.execute(
                    """
                    INSERT INTO shoe_photos (product_id, angle_type, file_path, is_valid)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(product_id, angle_type)
                    DO UPDATE SET file_path = excluded.file_path, is_valid = 1, uploaded_at = CURRENT_TIMESTAMP
                    """,
                    (product_id, angle, file_url),
                )
                updated += 1
    print(f"Berhasil memperbarui {updated} foto untuk produk #1 s.d. #4 di database.")


if __name__ == "__main__":
    apply_sample_photos()
