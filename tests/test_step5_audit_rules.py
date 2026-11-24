from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.backup import create_backup
from app.main import app
from app.seed import seed_database


@pytest.fixture
def step5_env(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_step5.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return test_db, tmp_path


def test_audit_log_page_tc015(step5_env):
    client = TestClient(app)
    client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})

    res = client.get("/admin/audit")
    assert res.status_code == 200
    assert "SEED_INITIAL" in res.text
    assert "Admin COE Local Thrift" in res.text

    res_filtered = client.get("/admin/audit?product_id=1")
    assert res_filtered.status_code == 200
    assert "#1 Nike" in res_filtered.text


def test_rules_rbac_and_versioning_fr019_nfr002(step5_env):
    # 1. Admin operasional (role='admin') boleh lihat, tapi TIDAK boleh ubah aturan (403)
    admin_client = TestClient(app)
    admin_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})
    assert admin_client.get("/admin/rules").status_code == 200

    payload = {
        "weight_brand": 20,
        "weight_condition": 45,
        "weight_usage": 20,
        "weight_originality": 15,
        "threshold_a": 82,
        "threshold_b": 68,
        "threshold_c": 52,
        "discount_a": 25,
        "discount_b": 40,
        "discount_c": 55,
        "discount_d": 80,
        "rounding_unit": 5000,
        "change_reason": "Uji penyesuaian aturan",
    }
    assert admin_client.post("/admin/rules", data=payload).status_code == 403

    # 2. Manajemen COE (role='management') berwenang membuat versi aturan baru
    mgmt_client = TestClient(app)
    mgmt_client.post("/admin/login", data={"email": "manajemen@localthrift.id", "password": "manajemen123"})

    # Total bobot != 100 wajib ditolak (400)
    bad_payload = dict(payload, weight_brand=30)
    assert mgmt_client.post("/admin/rules", data=bad_payload).status_code == 400

    # Payload valid -> membuat v2 dan mencatat log UBAH_ATURAN
    ok = mgmt_client.post("/admin/rules", data=payload, follow_redirects=False)
    assert ok.status_code == 303
    assert "msg=updated" in ok.headers["location"]

    health = mgmt_client.get("/health").json()
    assert health["active_rule_version"] == 2

    audit_res = mgmt_client.get("/admin/audit?action_type=UBAH_ATURAN")
    assert audit_res.status_code == 200
    assert "Uji penyesuaian aturan" in audit_res.text


def test_database_backup_nfr010(step5_env):
    test_db, tmp_path = step5_env
    backup_file = create_backup(db_path=test_db, backup_dir=tmp_path / "backups")
    assert backup_file.exists()
    with sqlite3.connect(str(backup_file)) as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM shoes").fetchone()[0]
        assert cnt == 4
