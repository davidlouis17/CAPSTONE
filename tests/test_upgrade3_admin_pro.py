from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database


@pytest.fixture
def admin_pro_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_up3.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_csv_exports_require_auth_and_return_valid_csv(admin_pro_client: TestClient):
    # Tanpa login wajib redirect ke /admin/login (NFR-002)
    assert admin_pro_client.get("/admin/export/shoes.csv", follow_redirects=False).status_code == 303
    assert admin_pro_client.get("/admin/export/audit.csv", follow_redirects=False).status_code == 303

    # Login admin
    admin_pro_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})

    r_shoes = admin_pro_client.get("/admin/export/shoes.csv")
    assert r_shoes.status_code == 200
    assert "text/csv" in r_shoes.headers["content-type"]
    assert "product_id,brand,model_name" in r_shoes.text
    assert "Nike" in r_shoes.text

    r_audit = admin_pro_client.get("/admin/export/audit.csv")
    assert r_audit.status_code == 200
    assert "text/csv" in r_audit.headers["content-type"]
    assert "log_id,timestamp,admin_name" in r_audit.text
    assert "SEED_INITIAL" in r_audit.text


def test_dashboard_charts_stepper_and_live_preview(admin_pro_client: TestClient):
    admin_pro_client.post("/admin/login", data={"email": "admin@localthrift.id", "password": "admin123"})

    dash = admin_pro_client.get("/admin")
    assert dash.status_code == 200
    assert "gradeChart" in dash.text
    assert "statusChart" in dash.text
    assert "/admin/export/shoes.csv" in dash.text

    detail = admin_pro_client.get("/admin/shoes/1")
    assert detail.status_code == 200
    assert "Stepper Alur Kurasi" in detail.text
    assert "previewAnglePhoto" in detail.text
