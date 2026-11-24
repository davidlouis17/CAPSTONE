from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database


@pytest.fixture
def ui_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_up1.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_public_catalog_and_detail_upgrades(ui_client: TestClient):
    res = ui_client.get("/catalog")
    assert res.status_code == 200
    assert "-30%" in res.text
    assert "Standar Kurasi" in res.text

    detail = ui_client.get("/catalog/1")
    assert detail.status_code == 200
    assert "Tanya / Pesan via WhatsApp COE" in detail.text
    assert "photo-lightbox" in detail.text
    # Privasi NFR-011 tetap terjaga
    assert "struk asli terverifikasi" not in detail.text


def test_custom_404_page_for_grade_d(ui_client: TestClient):
    res = ui_client.get("/catalog/4")
    assert res.status_code == 404
    assert "Produk atau Halaman Tidak Tersedia" in res.text
