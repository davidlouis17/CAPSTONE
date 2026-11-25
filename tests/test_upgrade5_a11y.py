from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database


@pytest.fixture
def a11y_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_a11y.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_accessibility_widget_and_assets_present(a11y_client: TestClient):
    res = a11y_client.get("/catalog")
    assert res.status_code == 200
    assert "skip-to-content" in res.text
    assert 'id="a11y-fab"' in res.text
    assert 'id="a11y-panel"' in res.text
    assert "/static/js/accessibility.js" in res.text
    assert "/static/css/accessibility.css" in res.text

    assert a11y_client.get("/static/js/accessibility.js").status_code == 200
    assert a11y_client.get("/static/css/accessibility.css").status_code == 200
