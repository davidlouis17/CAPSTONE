from io import BytesIO
from pathlib import Path
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_database


def _make_png_bytes(color=(120, 140, 160)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def admin_client(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_admin.db"
    test_uploads = tmp_path / "uploads"
    test_uploads.mkdir(parents=True, exist_ok=True)
    seed_database(test_db)

    monkeypatch.setattr("app.database.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.config.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.main.DATABASE_PATH", test_db)
    monkeypatch.setattr("app.routers.admin.UPLOAD_DIR", test_uploads)
    monkeypatch.setattr("app.config.UPLOAD_DIR", test_uploads)
    return TestClient(app)


def test_admin_auth_guard_tc001_tc002(admin_client: TestClient):
    # TC-002: Akses halaman admin tanpa login wajib ditolak / redirect ke /admin/login
    res_unauth = admin_client.get("/admin", follow_redirects=False)
    assert res_unauth.status_code == 303
    assert res_unauth.headers["location"] == "/admin/login"

    # Login salah -> 401
    res_bad = admin_client.post(
        "/admin/login",
        data={"email": "admin@localthrift.id", "password": "salah"},
    )
    assert res_bad.status_code == 401

    # TC-001: Login kredensial valid -> masuk dasbor
    res_ok = admin_client.post(
        "/admin/login",
        data={"email": "admin@localthrift.id", "password": "admin123"},
        follow_redirects=False,
    )
    assert res_ok.status_code == 303
    assert res_ok.headers["location"] == "/admin"
    assert admin_client.get("/admin").status_code == 200


def test_input_validation_verification_and_4_angle_photos_tc003_to_tc007(admin_client: TestClient):
    # Login terlebih dahulu
    admin_client.post(
        "/admin/login",
        data={"email": "admin@localthrift.id", "password": "admin123"},
    )

    # TC-004: Harga negatif wajib ditolak (400)
    res_neg = admin_client.post(
        "/admin/shoes/new",
        data={
            "brand": "Adidas",
            "model_name": "Samba OG",
            "size_eu": "42",
            "usage_duration": "< 6 bulan",
            "purchase_price": "-50000",
            "reference_new_price": "2200000",
            "originality_status": "struk_dan_box",
        },
    )
    assert res_neg.status_code == 400
    assert "negatif" in res_neg.text.lower()

    # TC-003: Input data wajib lengkap & valid -> tersimpan dengan ID produk baru
    res_create = admin_client.post(
        "/admin/shoes/new",
        data={
            "brand": "Adidas",
            "model_name": "Samba OG White",
            "size_eu": "42",
            "usage_duration": "< 6 bulan",
            "purchase_price": "2100000",
            "reference_new_price": "2200000",
            "originality_status": "struk_dan_box",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303
    loc = res_create.headers["location"]
    product_id = int(loc.split("/admin/shoes/")[1].split("?")[0])

    # TC-005 & TC-007: Belum verifikasi fisik dan foto belum lengkap -> ready_for_ai False
    r0 = admin_client.get(f"/api/admin/shoes/{product_id}/readiness").json()
    assert r0["physical_verified"] is False
    assert r0["photos_complete"] is False
    assert set(r0["missing_angles"]) == {"top", "right", "left", "bottom"}
    assert r0["ready_for_ai"] is False

    # Upload file rusak wajib ditolak (FR-007)
    res_corrupt = admin_client.post(
        f"/admin/shoes/{product_id}/photos",
        files={"top": ("broken.png", b"bukan-gambar-valid", "image/png")},
    )
    assert res_corrupt.status_code == 400

    # Upload hanya 2 sisi -> masih belum lengkap (TC-005)
    img_bytes = _make_png_bytes()
    res_partial = admin_client.post(
        f"/admin/shoes/{product_id}/photos",
        files={
            "top": ("top.png", img_bytes, "image/png"),
            "right": ("right.png", img_bytes, "image/png"),
        },
        follow_redirects=False,
    )
    assert res_partial.status_code == 303
    r1 = admin_client.get(f"/api/admin/shoes/{product_id}/readiness").json()
    assert r1["photos_complete"] is False
    assert set(r1["missing_angles"]) == {"left", "bottom"}

    # Lengkapi 2 sisi sisanya (TC-006)
    res_rest = admin_client.post(
        f"/admin/shoes/{product_id}/photos",
        files={
            "left": ("left.png", img_bytes, "image/png"),
            "bottom": ("bottom.png", img_bytes, "image/png"),
        },
        follow_redirects=False,
    )
    assert res_rest.status_code == 303
    r2 = admin_client.get(f"/api/admin/shoes/{product_id}/readiness").json()
    assert r2["photos_complete"] is True
    assert r2["ready_for_ai"] is False  # Masih gagal BR-001 karena physical_verified = False

    # Loloskan Physical Verification Gate (FR-005 / BR-001)
    res_verify = admin_client.post(
        f"/admin/shoes/{product_id}/verify",
        data={"physical_verified": "on", "verification_notes": "Fisik bagus, struk cocok."},
        follow_redirects=False,
    )
    assert res_verify.status_code == 303

    r3 = admin_client.get(f"/api/admin/shoes/{product_id}/readiness").json()
    assert r3["physical_verified"] is True
    assert r3["photos_complete"] is True
    assert r3["ready_for_ai"] is True
