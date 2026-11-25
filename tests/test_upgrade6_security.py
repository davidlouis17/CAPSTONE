from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.auth import reset_all_login_attempts
from app.main import app
from app.seed import seed_database


@pytest.fixture
def up6_client(tmp_path: Path, monkeypatch):
    reset_all_login_attempts()
    test_db = tmp_path / "test_up6.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    yield TestClient(app)
    reset_all_login_attempts()


def test_login_rate_limiting(up6_client: TestClient):
    # 5 percobaan gagal -> 401
    for _ in range(5):
        r = up6_client.post(
            "/admin/login",
            data={"email": "admin@localthrift.id", "password": "salah"},
        )
        assert r.status_code == 401

    # Percobaan ke-6 wajib diblokir 429
    r_locked = up6_client.post(
        "/admin/login",
        data={"email": "admin@localthrift.id", "password": "admin123"},
    )
    assert r_locked.status_code == 429
    assert "Terlalu banyak percobaan login gagal" in r_locked.text


def test_catalog_eu_size_filter(up6_client: TestClient):
    r42 = up6_client.get("/api/catalog?size=42")
    assert r42.status_code == 200
    assert r42.json()["count"] == 1
    assert r42.json()["items"][0]["brand"] == "Nike"

    r41 = up6_client.get("/api/catalog?size=41")
    assert r41.status_code == 200
    assert r41.json()["count"] == 1
    assert r41.json()["items"][0]["brand"] == "New Balance"

    page = up6_client.get("/catalog?size=42")
    assert page.status_code == 200
    assert "EU 42" in page.text


def test_admin_shoe_detail_includes_mini_audit_timeline(up6_client: TestClient):
    up6_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})
    res = up6_client.get("/admin/shoes/1")
    assert res.status_code == 200
    assert "Riwayat Audit Produk" in res.text
    assert "SEED_INITIAL" in res.text
    assert "WIB" in res.text
