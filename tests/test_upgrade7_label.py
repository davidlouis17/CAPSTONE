from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.auth import reset_all_login_attempts
from app.main import app
from app.seed import seed_database


@pytest.fixture
def label_client(tmp_path: Path, monkeypatch):
    reset_all_login_attempts()
    test_db = tmp_path / "test_up7.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_hangtag_label_requires_auth_and_renders_qr_data(label_client: TestClient):
    # Tanpa login wajib redirect ke /admin/login
    assert label_client.get("/admin/shoes/1/label", follow_redirects=False).status_code == 303

    label_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})
    res = label_client.get("/admin/shoes/1/label")
    assert res.status_code == 200
    assert "LOCAL THRIFT" in res.text
    assert "Nike" in res.text
    assert "EU 42" in res.text
    assert "Grade A" in res.text
    assert "Rp 1.085.000" in res.text
    assert "/catalog/1" in res.text
    assert "window.print()" in res.text
