from io import BytesIO
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from app.auth import authenticate_admin, get_current_admin
from app.config import APP_NAME, UPLOAD_DIR
from app.database import db_session
from app.routers.catalog import ANGLE_LABELS, format_rupiah

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["rupiah"] = format_rupiah

router = APIRouter(tags=["Admin COE"])

REQUIRED_ANGLES = ("top", "right", "left", "bottom")
USAGE_DURATION_OPTIONS = ("< 6 bulan", "6 - 12 bulan", "1 - 2 tahun", "> 2 tahun")
ORIGINALITY_OPTIONS = (
    ("struk_dan_box", "Struk Asli & Box Lengkap"),
    ("barcode_terverifikasi", "Barcode / Tag Terverifikasi"),
    ("box_saja", "Box Asli Saja (Tanpa Struk)"),
    ("tanpa_bukti", "Tanpa Bukti Originalitas"),
)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


def _require_admin_redirect(request: Request) -> Optional[RedirectResponse]:
    if not get_current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


def _log_audit(
    conn,
    admin_id: int,
    action_type: str,
    product_id: Optional[int] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    correction_reason: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_logs
            (product_id, admin_id, action_type, old_value, new_value, correction_reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            admin_id,
            action_type,
            json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            correction_reason,
        ),
    )


def _validate_and_save_photo(product_id: int, angle: str, upload: UploadFile, content: bytes) -> tuple[bool, str]:
    """Validasi citra 4 sisi menggunakan Pillow dan simpan ke folder upload (FR-006, FR-007)."""
    if angle not in REQUIRED_ANGLES:
        return False, f"Sudut foto tidak dikenali: {angle}"
    if not content:
        return False, f"File foto sisi {ANGLE_LABELS[angle]} kosong."
    if len(content) > MAX_IMAGE_BYTES:
        return False, f"Ukuran foto sisi {ANGLE_LABELS[angle]} melebihi 8 MB."

    filename = upload.filename or f"{angle}.jpg"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"

    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError):
        return False, f"File foto sisi {ANGLE_LABELS[angle]} rusak atau bukan format gambar yang valid."

    target_dir = UPLOAD_DIR / f"shoe_{product_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"{angle}{ext}"
    target_path = target_dir / saved_name
    target_path.write_bytes(content)

    # Path publik relatif terhadap /static
    rel_url = f"/static/uploads/shoe_{product_id}/{saved_name}"
    return True, rel_url


def _get_shoe_workspace_data(product_id: int) -> Optional[dict]:
    with db_session() as conn:
        shoe_row = conn.execute(
            """
            SELECT s.*, a.name AS admin_name
            FROM shoes s
            JOIN admins a ON a.admin_id = s.admin_id
            WHERE s.product_id = ?
            """,
            (product_id,),
        ).fetchone()
        if not shoe_row:
            return None

        photo_rows = conn.execute(
            "SELECT angle_type, file_path, is_valid, uploaded_at FROM shoe_photos WHERE product_id = ?",
            (product_id,),
        ).fetchall()
        photo_map = {row["angle_type"]: dict(row) for row in photo_rows}

        eval_row = conn.execute(
            """
            SELECT * FROM evaluations
            WHERE product_id = ?
            ORDER BY created_at DESC, evaluation_id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()

    missing_angles = [
        angle for angle in REQUIRED_ANGLES
        if angle not in photo_map or not photo_map[angle]["is_valid"]
    ]
    shoe = dict(shoe_row)
    return {
        "shoe": shoe,
        "photo_map": photo_map,
        "missing_angles": missing_angles,
        "photos_complete": len(missing_angles) == 0,
        "ready_for_ai": bool(shoe["physical_verified"]) and len(missing_angles) == 0,
        "evaluation": dict(eval_row) if eval_row else None,
    }


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_admin(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"app_name": APP_NAME, "error": None, "email": ""},
    )


@router.post("/admin/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    admin = authenticate_admin(email, password)
    if not admin:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={
                "app_name": APP_NAME,
                "error": "Email atau kata sandi tidak valid.",
                "email": email.strip(),
            },
            status_code=401,
        )

    request.session["admin_id"] = admin["admin_id"]
    request.session["admin_name"] = admin["name"]
    request.session["admin_role"] = admin["role"]
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/logout")
def logout_submit(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                s.product_id,
                s.brand,
                s.model_name,
                s.size_eu,
                s.reference_new_price,
                s.physical_verified,
                s.process_status,
                s.created_at,
                (
                    SELECT COUNT(*) FROM shoe_photos p
                    WHERE p.product_id = s.product_id AND p.is_valid = 1
                ) AS valid_photo_count,
                (
                    SELECT e.final_grade FROM evaluations e
                    WHERE e.product_id = s.product_id
                    ORDER BY e.created_at DESC, e.evaluation_id DESC
                    LIMIT 1
                ) AS final_grade,
                (
                    SELECT e.final_price FROM evaluations e
                    WHERE e.product_id = s.product_id
                    ORDER BY e.created_at DESC, e.evaluation_id DESC
                    LIMIT 1
                ) AS final_price
            FROM shoes s
            ORDER BY s.created_at DESC, s.product_id DESC
            """
        ).fetchall()

    shoes = [dict(r) for r in rows]
    counts = {
        "total": len(shoes),
        "draft": sum(1 for s in shoes if s["process_status"] == "draft"),
        "pending_review": sum(1 for s in shoes if s["process_status"] == "pending_review"),
        "published": sum(1 for s in shoes if s["process_status"] == "published"),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "shoes": shoes,
            "counts": counts,
        },
    )


@router.get("/admin/shoes/new", response_class=HTMLResponse)
def new_shoe_page(request: Request):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    return templates.TemplateResponse(
        request=request,
        name="admin/shoe_form.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "usage_options": USAGE_DURATION_OPTIONS,
            "originality_options": ORIGINALITY_OPTIONS,
            "error": None,
            "form_data": {},
        },
    )


@router.post("/admin/shoes/new", response_class=HTMLResponse)
def create_shoe_submit(
    request: Request,
    brand: str = Form(...),
    model_name: str = Form(""),
    size_eu: str = Form(""),
    usage_duration: str = Form(...),
    purchase_price: str = Form(...),
    reference_new_price: str = Form(...),
    originality_status: str = Form(...),
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    form_data = {
        "brand": brand.strip(),
        "model_name": model_name.strip(),
        "size_eu": size_eu.strip(),
        "usage_duration": usage_duration.strip(),
        "purchase_price": purchase_price.strip(),
        "reference_new_price": reference_new_price.strip(),
        "originality_status": originality_status.strip(),
    }

    errors: list[str] = []
    if not form_data["brand"]:
        errors.append("Merek sepatu wajib diisi.")
    if form_data["usage_duration"] not in USAGE_DURATION_OPTIONS:
        errors.append("Pilihan lama pemakaian tidak valid.")
    valid_orig_keys = {k for k, _ in ORIGINALITY_OPTIONS}
    if form_data["originality_status"] not in valid_orig_keys:
        errors.append("Status bukti originalitas tidak valid.")

    try:
        parsed_purchase = float(form_data["purchase_price"])
        if parsed_purchase < 0:
            errors.append("Harga beli awal tidak boleh negatif.")
    except ValueError:
        parsed_purchase = -1.0
        errors.append("Harga beli awal harus berupa angka yang valid.")

    try:
        parsed_ref = float(form_data["reference_new_price"])
        if parsed_ref <= 0:
            errors.append("Harga baru referensi harus lebih besar dari 0.")
    except ValueError:
        parsed_ref = -1.0
        errors.append("Harga baru referensi harus berupa angka yang valid.")

    if errors:
        return templates.TemplateResponse(
            request=request,
            name="admin/shoe_form.html",
            context={
                "app_name": APP_NAME,
                "admin": admin,
                "usage_options": USAGE_DURATION_OPTIONS,
                "originality_options": ORIGINALITY_OPTIONS,
                "error": " ".join(errors),
                "form_data": form_data,
            },
            status_code=400,
        )

    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO shoes (
                admin_id, brand, model_name, size_eu, usage_duration,
                purchase_price, reference_new_price, originality_status,
                physical_verified, process_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft')
            """,
            (
                admin["admin_id"],
                form_data["brand"],
                form_data["model_name"],
                form_data["size_eu"],
                form_data["usage_duration"],
                parsed_purchase,
                parsed_ref,
                form_data["originality_status"],
            ),
        )
        product_id = cur.lastrowid
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type="INPUT_DATA",
            product_id=product_id,
            new_value={
                "brand": form_data["brand"],
                "model_name": form_data["model_name"],
                "reference_new_price": parsed_ref,
                "process_status": "draft",
            },
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=created", status_code=303)


@router.get("/admin/shoes/{product_id}", response_class=HTMLResponse)
def admin_shoe_detail(
    request: Request,
    product_id: int,
    msg: str = "",
    err: str = "",
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    workspace = _get_shoe_workspace_data(product_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

    flash_messages = {
        "created": "Data sepatu tersimpan sebagai draf. Lanjutkan verifikasi fisik dan unggah 4 sisi foto.",
        "verified": "Status verifikasi fisik berhasil diperbarui dan tercatat di log audit.",
        "photos_saved": "Foto berhasil divalidasi dan disimpan.",
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/shoe_detail.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "workspace": workspace,
            "angle_labels": ANGLE_LABELS,
            "required_angles": REQUIRED_ANGLES,
            "flash_success": flash_messages.get(msg, ""),
            "flash_error": err,
        },
    )


@router.post("/admin/shoes/{product_id}/verify")
def verify_shoe_physical(
    request: Request,
    product_id: int,
    physical_verified: Optional[str] = Form(None),
    verification_notes: str = Form(""),
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    is_verified = 1 if physical_verified == "on" else 0
    notes = verification_notes.strip()

    with db_session() as conn:
        existing = conn.execute(
            "SELECT physical_verified, verification_notes FROM shoes WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

        conn.execute(
            "UPDATE shoes SET physical_verified = ?, verification_notes = ? WHERE product_id = ?",
            (is_verified, notes, product_id),
        )
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type="VERIFIKASI_FISIK",
            product_id=product_id,
            old_value={"physical_verified": bool(existing["physical_verified"])},
            new_value={"physical_verified": bool(is_verified), "notes": notes},
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=verified", status_code=303)


@router.post("/admin/shoes/{product_id}/photos")
async def upload_shoe_photos(
    request: Request,
    product_id: int,
    top: Optional[UploadFile] = File(None),
    right: Optional[UploadFile] = File(None),
    left: Optional[UploadFile] = File(None),
    bottom: Optional[UploadFile] = File(None),
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    with db_session() as conn:
        exists = conn.execute("SELECT product_id FROM shoes WHERE product_id = ?", (product_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

    uploads = {"top": top, "right": right, "left": left, "bottom": bottom}
    saved_angles: list[str] = []
    errors: list[str] = []

    with db_session() as conn:
        for angle, upload in uploads.items():
            if upload is None or not upload.filename:
                continue
            content = await upload.read()
            ok, result = _validate_and_save_photo(product_id, angle, upload, content)
            if not ok:
                errors.append(result)
                continue

            conn.execute(
                """
                INSERT INTO shoe_photos (product_id, angle_type, file_path, is_valid)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(product_id, angle_type)
                DO UPDATE SET file_path = excluded.file_path, is_valid = 1, uploaded_at = CURRENT_TIMESTAMP
                """,
                (product_id, angle, result),
            )
            saved_angles.append(angle)

        if saved_angles:
            _log_audit(
                conn,
                admin_id=admin["admin_id"],
                action_type="UNGGAH_FOTO",
                product_id=product_id,
                new_value={"angles": saved_angles},
            )

    if errors:
        workspace = _get_shoe_workspace_data(product_id)
        return templates.TemplateResponse(
            request=request,
            name="admin/shoe_detail.html",
            context={
                "app_name": APP_NAME,
                "admin": admin,
                "workspace": workspace,
                "angle_labels": ANGLE_LABELS,
                "required_angles": REQUIRED_ANGLES,
                "flash_success": "",
                "flash_error": " ".join(errors),
            },
            status_code=400,
        )

    if not saved_angles:
        workspace = _get_shoe_workspace_data(product_id)
        return templates.TemplateResponse(
            request=request,
            name="admin/shoe_detail.html",
            context={
                "app_name": APP_NAME,
                "admin": admin,
                "workspace": workspace,
                "angle_labels": ANGLE_LABELS,
                "required_angles": REQUIRED_ANGLES,
                "flash_success": "",
                "flash_error": "Pilih minimal satu file foto (Atas, Kanan, Kiri, atau Bawah) sebelum mengunggah.",
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=photos_saved", status_code=303)


@router.get("/api/admin/shoes/{product_id}/readiness", response_class=JSONResponse)
def check_shoe_readiness_api(request: Request, product_id: int):
    """Cek kesiapan sepatu sebelum inferensi AI (BR-001, FR-007, TC-005, TC-007)."""
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Otentikasi admin diperlukan.")

    workspace = _get_shoe_workspace_data(product_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

    return {
        "product_id": product_id,
        "physical_verified": bool(workspace["shoe"]["physical_verified"]),
        "photos_complete": workspace["photos_complete"],
        "missing_angles": workspace["missing_angles"],
        "ready_for_ai": workspace["ready_for_ai"],
    }
