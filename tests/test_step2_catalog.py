from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import catalog as catalog_module
from app.seed import seed_database


@pytest.fixture
def seeded_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_catalog.db"
    seed_database(test_db)
    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    return TestClient(app)


def test_catalog_shows_only_published_non_grade_d(seeded_client: TestClient):
    res = seeded_client.get("/api/catalog")
    assert res.status_code == 200
    data = res.json()
    # Seed berisi 4 sepatu: 2 published (Grade A Nike, Grade B New Balance),
    # 1 pending_review (Converse), 1 approved Grade D (Vans)
    assert data["count"] == 2
    brands = {item["brand"] for item in data["items"]}
    assert brands == {"Nike", "New Balance"}
    assert all(item["grade"] != "D" for item in data["items"])

    # Pastikan data internal tidak bocor di API publik (NFR-011 / TC-016)
    for item in data["items"]:
        assert "purchase_price" not in item
        assert "verification_notes" not in item
        assert "admin_id" not in item
        assert "correction_reason" not in item


def test_catalog_search_filter_and_sort(seeded_client: TestClient):
    res_q = seeded_client.get("/api/catalog?q=nike")
    assert res_q.status_code == 200
    assert res_q.json()["count"] == 1
    assert res_q.json()["items"][0]["brand"] == "Nike"

    res_grade = seeded_client.get("/api/catalog?grade=B")
    assert res_grade.status_code == 200
    assert res_grade.json()["count"] == 1
    assert res_grade.json()["items"][0]["brand"] == "New Balance"

    res_sort = seeded_client.get("/api/catalog?sort=price_asc")
    prices = [item["price"] for item in res_sort.json()["items"]]
    assert prices == sorted(prices)


def test_catalog_detail_and_privacy_rules(seeded_client: TestClient):
    # Product 1 = Nike published Grade A
    res_ok = seeded_client.get("/catalog/1")
    assert res_ok.status_code == 200
    body = res_ok.text
    assert "Nike" in body
    assert "Grade A" in body
    assert "Sisi Atas" in body
    assert "Sisi Bawah (Sol)" in body
    # Catatan internal verifikasi admin tidak boleh tampil di publik (NFR-011)
    assert "struk asli terverifikasi" not in body

    # Product 3 = pending_review (Converse) -> wajib 404
    assert seeded_client.get("/catalog/3").status_code == 404

    # Product 4 = Grade D (Vans) -> wajib 404 (BR-009 / TC-013)
    assert seeded_client.get("/catalog/4").status_code == 404
