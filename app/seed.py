import json
from pathlib import Path
from typing import Optional

from app.database import db_session, init_db
from app.security import hash_password


def seed_database(db_path: Optional[Path] = None) -> dict:
    """Isi data awal (idempoten): akun admin, aturan bisnis v1, dan 4 contoh sepatu."""
    init_db(db_path)
    summary = {"admins": 0, "rules": 0, "shoes": 0}

    with db_session(db_path) as conn:
        # 1. Akun Admin & Manajemen COE
        default_admins = [
            ("Admin COE Local Thrift", "admin@localthrift.id", "admin123", "admin"),
            ("Manajemen COE", "manajemen@localthrift.id", "manajemen123", "management"),
        ]
        for name, email, raw_pw, role in default_admins:
            exists = conn.execute(
                "SELECT admin_id FROM admins WHERE email = ?", (email,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO admins (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                    (name, email, hash_password(raw_pw), role),
                )
                summary["admins"] += 1

        admin_row = conn.execute(
            "SELECT admin_id FROM admins WHERE email = ?", ("admin@localthrift.id",)
        ).fetchone()
        admin_id = admin_row["admin_id"]

        # 2. Aturan Sistem Versi 1 (BR-003 s.d. BR-006)
        rule_exists = conn.execute(
            "SELECT rule_id FROM system_rules WHERE version = 1"
        ).fetchone()
        if not rule_exists:
            conn.execute(
                """
                INSERT INTO system_rules
                    (version, criteria_weights, grade_thresholds, discount_percentage, rounding_unit, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    1,
                    json.dumps({"brand": 25, "condition": 40, "usage_duration": 20, "originality": 15}),
                    json.dumps({"A": 80, "B": 65, "C": 50, "D": 0}),
                    json.dumps({"A": 30, "B": 45, "C": 60, "D": 80}),
                    5000,
                ),
            )
            summary["rules"] += 1

        # 3. Data Contoh Sepatu (hanya jika tabel shoes masih kosong)
        shoe_count = conn.execute("SELECT COUNT(*) AS cnt FROM shoes").fetchone()["cnt"]
        if shoe_count == 0:
            sample_shoes = [
                {
                    "brand": "Nike",
                    "model_name": "Air Force 1 '07 Low White",
                    "size_eu": "42",
                    "usage_duration": "< 6 bulan",
                    "purchase_price": 1549000,
                    "reference_new_price": 1549000,
                    "originality_status": "struk_dan_box",
                    "physical_verified": 1,
                    "verification_notes": "Upper bersih, outsole minim kikis, struk asli terverifikasi.",
                    "process_status": "published",
                    "condition_score": 90.0,
                    "condition_label": "Sangat Baik",
                    "criteria_breakdown": {"brand": 23.0, "condition": 36.0, "usage_duration": 18.0, "originality": 15.0},
                    "total_points": 92.0,
                    "assigned_grade": "A",
                    "recommended_price": 1085000,
                    "final_grade": "A",
                    "final_price": 1085000,
                },
                {
                    "brand": "New Balance",
                    "model_name": "574 Core Grey",
                    "size_eu": "41",
                    "usage_duration": "6 - 12 bulan",
                    "purchase_price": 1499000,
                    "reference_new_price": 1499000,
                    "originality_status": "barcode_terverifikasi",
                    "physical_verified": 1,
                    "verification_notes": "Suede terawat, sedikit lipatan wajar di toebox.",
                    "process_status": "published",
                    "condition_score": 78.0,
                    "condition_label": "Baik",
                    "criteria_breakdown": {"brand": 22.0, "condition": 31.2, "usage_duration": 14.0, "originality": 12.0},
                    "total_points": 79.2,
                    "assigned_grade": "B",
                    "recommended_price": 825000,
                    "final_grade": "B",
                    "final_price": 825000,
                },
                {
                    "brand": "Converse",
                    "model_name": "Chuck 70 High Black",
                    "size_eu": "43",
                    "usage_duration": "1 - 2 tahun",
                    "purchase_price": 1099000,
                    "reference_new_price": 1099000,
                    "originality_status": "barcode_terverifikasi",
                    "physical_verified": 1,
                    "verification_notes": "Kanvas masih kokoh, foxing sedikit menguning.",
                    "process_status": "pending_review",
                    "condition_score": 64.0,
                    "condition_label": "Cukup",
                    "criteria_breakdown": {"brand": 19.0, "condition": 25.6, "usage_duration": 10.0, "originality": 10.0},
                    "total_points": 64.6,
                    "assigned_grade": "C",
                    "recommended_price": 440000,
                    "final_grade": "C",
                    "final_price": 440000,
                },
                {
                    "brand": "Vans",
                    "model_name": "Old Skool Black White",
                    "size_eu": "40",
                    "usage_duration": "> 2 tahun",
                    "purchase_price": 999000,
                    "reference_new_price": 999000,
                    "originality_status": "tanpa_bukti",
                    "physical_verified": 1,
                    "verification_notes": "Sol belakang aus signifikan; grade terendah ditahan dari katalog.",
                    "process_status": "approved",
                    "condition_score": 38.0,
                    "condition_label": "Kurang Layak",
                    "criteria_breakdown": {"brand": 18.0, "condition": 15.2, "usage_duration": 5.0, "originality": 3.0},
                    "total_points": 41.2,
                    "assigned_grade": "D",
                    "recommended_price": 200000,
                    "final_grade": "D",
                    "final_price": 200000,
                },
            ]

            for item in sample_shoes:
                cur = conn.execute(
                    """
                    INSERT INTO shoes (
                        admin_id, brand, model_name, size_eu, usage_duration,
                        purchase_price, reference_new_price, originality_status,
                        physical_verified, verification_notes, process_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        admin_id,
                        item["brand"],
                        item["model_name"],
                        item["size_eu"],
                        item["usage_duration"],
                        item["purchase_price"],
                        item["reference_new_price"],
                        item["originality_status"],
                        item["physical_verified"],
                        item["verification_notes"],
                        item["process_status"],
                    ),
                )
                product_id = cur.lastrowid

                for angle in ("top", "right", "left", "bottom"):
                    conn.execute(
                        """
                        INSERT INTO shoe_photos (product_id, angle_type, file_path, is_valid)
                        VALUES (?, ?, ?, 1)
                        """,
                        (product_id, angle, f"/static/img/placeholder-{angle}.svg"),
                    )

                conn.execute(
                    """
                    INSERT INTO evaluations (
                        product_id, condition_score, condition_label, criteria_breakdown,
                        total_points, assigned_grade, recommended_price,
                        final_grade, final_price, rule_version, model_version, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'cnn-visual-v1', 'success')
                    """,
                    (
                        product_id,
                        item["condition_score"],
                        item["condition_label"],
                        json.dumps(item["criteria_breakdown"]),
                        item["total_points"],
                        item["assigned_grade"],
                        item["recommended_price"],
                        item["final_grade"],
                        item["final_price"],
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO audit_logs (product_id, admin_id, action_type, old_value, new_value, correction_reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        admin_id,
                        "SEED_INITIAL",
                        None,
                        json.dumps({"grade": item["final_grade"], "status": item["process_status"]}),
                        "Data awal contoh kurasi Local Thrift",
                    ),
                )
                summary["shoes"] += 1

    return summary


if __name__ == "__main__":
    result = seed_database()
    print(f"Seed selesai: {result}")
