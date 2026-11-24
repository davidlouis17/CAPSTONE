from io import BytesIO
from pathlib import Path
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from app.database import db_session
from app.main import app
from app.seed import seed_database
from app.services.rule_engine import calculate_grade_and_price
from ml.evaluate_model import compute_classification_report


def _make_png(color=(165, 165, 165)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (224, 224), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def step4_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_step4.db"
    test_uploads = tmp_path / "uploads"
    test_uploads.mkdir(parents=True, exist_ok=True)
    seed_database(test_db)

    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.routers.admin.UPLOAD_DIR", test_uploads)
    monkeypatch.setattr("app.config.UPLOAD_DIR", test_uploads)
    client = TestClient(app)
    client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})
    return client, test_db


def test_deterministic_rule_engine_tc008_tc009(tmp_path: Path):
    test_db = tmp_path / "rule_test.db"
    seed_database(test_db)

    res_a = calculate_grade_and_price(
        brand="Nike",
        condition_score=90.0,
        usage_duration="< 6 bulan",
        originality_status="struk_dan_box",
        reference_new_price=1_000_000,
        db_path=test_db,
    )
    assert res_a.assigned_grade == "A"
    assert res_a.discount_pct == 30.0
    assert res_a.recommended_price == 700_000.0

    res_d = calculate_grade_and_price(
        brand="UnknownBrand",
        condition_score=30.0,
        usage_duration="> 2 tahun",
        originality_status="tanpa_bukti",
        reference_new_price=1_000_000,
        db_path=test_db,
    )
    assert res_d.assigned_grade == "D"
    assert res_d.discount_pct == 80.0
    assert res_d.recommended_price == 200_000.0


def test_full_evaluation_correction_and_publication_flow_tc010_to_tc014(step4_client):
    client, test_db = step4_client

    # Buat sepatu baru
    r_new = client.post(
        "/admin/shoes/new",
        data={
            "brand": "Nike",
            "model_name": "Dunk Low Panda",
            "size_eu": "42",
            "usage_duration": "< 6 bulan",
            "purchase_price": "1500000",
            "reference_new_price": "1600000",
            "originality_status": "struk_dan_box",
        },
        follow_redirects=False,
    )
    pid = int(r_new.headers["location"].split("/admin/shoes/")[1].split("?")[0])

    # Loloskan Physical Verification Gate & unggah 4 foto valid
    client.post(f"/admin/shoes/{pid}/verify", data={"physical_verified": "on", "verification_notes": "Bagus"})
    png = _make_png()
    client.post(
        f"/admin/shoes/{pid}/photos",
        files={
            "top": ("top.png", png, "image/png"),
            "right": ("right.png", png, "image/png"),
            "left": ("left.png", png, "image/png"),
            "bottom": ("bottom.png", png, "image/png"),
        },
    )

    # Jalankan evaluasi AI + Rule Engine
    r_eval = client.post(f"/admin/shoes/{pid}/evaluate", follow_redirects=False)
    assert r_eval.status_code == 303
    assert "msg=evaluated" in r_eval.headers["location"]

    # TC-010: Koreksi tanpa alasan wajib ditolak (400)
    r_bad_corr = client.post(
        f"/admin/shoes/{pid}/correct",
        data={"final_grade": "B", "final_price": "900000", "correction_reason": "   "},
    )
    assert r_bad_corr.status_code == 400

    # TC-010: Koreksi dengan alasan tersimpan & mempertahankan assigned_grade awal
    r_corr = client.post(
        f"/admin/shoes/{pid}/correct",
        data={"final_grade": "B", "final_price": "900000", "correction_reason": "Ada crease halus di toebox"},
        follow_redirects=False,
    )
    assert r_corr.status_code == 303
    with db_session(test_db) as conn:
        ev = conn.execute("SELECT * FROM evaluations WHERE product_id = ?", (pid,)).fetchone()
        assert ev["assigned_grade"] != ev["final_grade"] or ev["recommended_price"] != ev["final_price"]
        assert ev["final_grade"] == "B"
        assert ev["final_price"] == 900000.0

    # TC-012: Setujui publikasi Grade B -> muncul di katalog publik
    r_pub = client.post(f"/admin/shoes/{pid}/decision", data={"decision": "approve"}, follow_redirects=False)
    assert r_pub.status_code == 303
    assert "msg=published" in r_pub.headers["location"]
    assert client.get(f"/catalog/{pid}").status_code == 200

    # TC-013: Jika dikoreksi ke Grade D lalu disetujui -> ditahan dari katalog publik (BR-009)
    client.post(
        f"/admin/shoes/{pid}/correct",
        data={"final_grade": "D", "final_price": "300000", "correction_reason": "Sol terkelupas saat cek ulang"},
    )
    r_hold = client.post(f"/admin/shoes/{pid}/decision", data={"decision": "approve"}, follow_redirects=False)
    assert "msg=approved_withheld" in r_hold.headers["location"]
    assert client.get(f"/catalog/{pid}").status_code == 404

    # TC-011: Tolak publikasi -> status rejected & tidak muncul di katalog
    r_rej = client.post(f"/admin/shoes/{pid}/decision", data={"decision": "reject"}, follow_redirects=False)
    assert "msg=rejected" in r_rej.headers["location"]
    assert client.get(f"/catalog/{pid}").status_code == 404


def test_ml_failure_handling_tc014(step4_client):
    client, test_db = step4_client
    # Ubah path foto product #3 menjadi tidak ada agar ML gagal
    with db_session(test_db) as conn:
        conn.execute(
            "UPDATE shoe_photos SET file_path = '/static/uploads/tidak_ada.png' WHERE product_id = 3 AND angle_type = 'top'"
        )
    r_fail = client.post("/admin/shoes/3/evaluate")
    assert r_fail.status_code == 422
    with db_session(test_db) as conn:
        status = conn.execute("SELECT process_status FROM shoes WHERE product_id = 3").fetchone()["process_status"]
        assert status == "ml_failed"
    assert client.get("/catalog/3").status_code == 404


def test_model_evaluation_metrics_tc017():
    rep = compute_classification_report(
        ["Sangat Baik", "Baik", "Cukup", "Kurang Layak"],
        ["Sangat Baik", "Baik", "Cukup", "Kurang Layak"],
    )
    assert rep["accuracy"] == 1.0
    assert rep["macro_f1"] == 1.0
