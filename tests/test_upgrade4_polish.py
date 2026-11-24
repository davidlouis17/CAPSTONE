from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.admin_governance import format_wib
from app.seed import seed_database


@pytest.fixture
def polish_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_up4.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_wib_timestamp_formatter():
    assert format_wib("2026-11-24 17:19:00") == "25 Nov 2026, 00:19 WIB"
    assert format_wib(None) == "-"


def test_custom_404_on_unknown_route_and_wib_in_audit(polish_client: TestClient):
    res_404 = polish_client.get("/halaman-tidak-ditemukan-xyz")
    assert res_404.status_code == 404
    assert "ERROR 404" in res_404.text
    assert "Kembali ke Katalog" in res_404.text

    polish_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})
    res_audit = polish_client.get("/admin/audit")
    assert res_audit.status_code == 200
    assert "WIB" in res_audit.text
