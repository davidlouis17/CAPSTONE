from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from app.auth import (
    authenticate_admin,
    check_login_rate_limit,
    clear_failed_logins,
    get_current_admin,
    record_failed_login,
)
from app.config import APP_NAME, UPLOAD_DIR
from app.database import db_session
from app.routers.catalog import ANGLE_LABELS, format_rupiah
from app.services.rule_engine import calculate_grade_and_price
from ml.shoe_evaluator import MLEvaluationError, evaluate_shoe_photos

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["rupiah"] = format_rupiah

WIB_TZ = timezone(timedelta(hours=7))
MONTH_ID = (
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
)


def _format_wib(raw_ts: Optional[str]) -> str:
    if not raw_ts:
        return "-"
    text = str(raw_ts).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt_utc = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            dt_wib = dt_utc.astimezone(WIB_TZ)
            return f"{dt_wib.day:02d} {MONTH_ID[dt_wib.month]} {dt_wib.year}, {dt_wib.strftime('%H:%M')} WIB"
        except ValueError:
            continue
    return text


templates.env.filters["wib"] = _format_wib

router = APIRouter(tags=["Admin COE"])

REQUIRED_ANGLES = ("top", "right", "left", "bottom")
ALLOWED_GRADES = ("A", "B", "C", "D")
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

        audit_rows = conn.execute(
            """
            SELECT l.log_id, l.action_type, l.old_value, l.new_value,
                   l.correction_reason, l.timestamp, a.name AS admin_name, a.role AS admin_role
            FROM audit_logs l
            JOIN admins a ON a.admin_id = l.admin_id
            WHERE l.product_id = ?
            ORDER BY l.timestamp DESC, l.log_id DESC
            LIMIT 10
            """,
            (product_id,),
        ).fetchall()

    missing_angles = [
        angle for angle in REQUIRED_ANGLES
        if angle not in photo_map or not photo_map[angle]["is_valid"]
    ]
    shoe = dict(shoe_row)
    evaluation = dict(eval_row) if eval_row else None
    if evaluation and evaluation.get("criteria_breakdown"):
        try:
            evaluation["breakdown_dict"] = json.loads(evaluation["criteria_breakdown"])
        except json.JSONDecodeError:
            evaluation["breakdown_dict"] = {}

    return {
        "shoe": shoe,
        "photo_map": photo_map,
        "missing_angles": missing_angles,
        "photos_complete": len(missing_angles) == 0,
        "ready_for_ai": bool(shoe["physical_verified"]) and len(missing_angles) == 0,
        "evaluation": evaluation,
        "audit_history": [dict(r) for r in audit_rows],
    }


def _render_shoe_detail(
    request: Request,
    admin: dict,
    product_id: int,
    flash_success: str = "",
    flash_error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    workspace = _get_shoe_workspace_data(product_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")
    return templates.TemplateResponse(
        request=request,
        name="admin/shoe_detail.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "workspace": workspace,
            "angle_labels": ANGLE_LABELS,
            "required_angles": REQUIRED_ANGLES,
            "allowed_grades": ALLOWED_GRADES,
            "flash_success": flash_success,
            "flash_error": flash_error,
        },
        status_code=status_code,
    )


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
    client_ip = request.client.host if request.client else "unknown"
    is_blocked, retry_after = check_login_rate_limit(client_ip, email)
    if is_blocked:
        mins = max(1, (retry_after + 59) // 60)
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={
                "app_name": APP_NAME,
                "error": f"Terlalu banyak percobaan login gagal. Coba lagi dalam sekitar {mins} menit.",
                "email": email.strip(),
            },
            status_code=429,
        )

    admin = authenticate_admin(email, password)
    if not admin:
        remaining = record_failed_login(client_ip, email)
        err_msg = (
            f"Email atau kata sandi tidak valid. Sisa percobaan: {remaining}."
            if remaining > 0
            else "Email atau kata sandi tidak valid. Akun dibatasi sementara selama 5 menit."
        )
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={
                "app_name": APP_NAME,
                "error": err_msg,
                "email": email.strip(),
            },
            status_code=401,
        )

    clear_failed_logins(client_ip, email)
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
        "draft": sum(1 for s in shoes if s["process_status"] in ("draft", "ml_failed")),
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

    flash_messages = {
        "created": "Data sepatu tersimpan sebagai draf. Lanjutkan verifikasi fisik dan unggah 4 sisi foto.",
        "verified": "Status verifikasi fisik berhasil diperbarui dan tercatat di log audit.",
        "photos_saved": "Foto berhasil divalidasi dan disimpan.",
        "evaluated": "Penilaian citra & kalkulasi aturan selesai. Silakan tinjau hasil sebelum publikasi.",
        "corrected": "Koreksi manual tersimpan. Nilai asli sistem tetap dipertahankan di riwayat audit.",
        "published": "Sepatu disetujui dan resmi tayang di katalog publik.",
        "approved_withheld": "Sepatu disetujui, namun karena Grade D otomatis ditahan agar tidak tampil di katalog publik (BR-009).",
        "rejected": "Publikasi sepatu ditolak dan tercatat di log audit.",
    }
    return _render_shoe_detail(
        request=request,
        admin=admin,
        product_id=product_id,
        flash_success=flash_messages.get(msg, ""),
        flash_error=err,
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
        return _render_shoe_detail(request, admin, product_id, flash_error=" ".join(errors), status_code=400)

    if not saved_angles:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Pilih minimal satu file foto (Atas, Kanan, Kiri, atau Bawah) sebelum mengunggah.",
            status_code=400,
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=photos_saved", status_code=303)


@router.post("/admin/shoes/{product_id}/evaluate")
def run_shoe_evaluation(request: Request, product_id: int):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    workspace = _get_shoe_workspace_data(product_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

    shoe = workspace["shoe"]
    if not shoe["physical_verified"]:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Penilaian ditolak: sepatu harus lolos Physical Verification Gate terlebih dahulu (BR-001).",
            status_code=400,
        )

    if not workspace["photos_complete"]:
        missing_str = ", ".join(ANGLE_LABELS[a] for a in workspace["missing_angles"])
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error=f"Penilaian ditolak: foto 4 sisi belum lengkap ({missing_str}) (FR-007).",
            status_code=400,
        )

    photo_paths = {angle: workspace["photo_map"][angle]["file_path"] for angle in REQUIRED_ANGLES}

    try:
        visual = evaluate_shoe_photos(photo_paths)
        calc = calculate_grade_and_price(
            brand=shoe["brand"],
            condition_score=visual.condition_score,
            usage_duration=shoe["usage_duration"],
            originality_status=shoe["originality_status"],
            reference_new_price=shoe["reference_new_price"],
        )
    except MLEvaluationError as exc:
        with db_session() as conn:
            conn.execute(
                "UPDATE shoes SET process_status = 'ml_failed' WHERE product_id = ?",
                (product_id,),
            )
            _log_audit(
                conn,
                admin_id=admin["admin_id"],
                action_type="EVALUASI_GAGAL",
                product_id=product_id,
                old_value={"process_status": shoe["process_status"]},
                new_value={"process_status": "ml_failed"},
                correction_reason=str(exc),
            )
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error=f"Modul penilaian citra gagal memproses foto: {exc}. Item ditandai ml_failed dan tidak dipublikasikan.",
            status_code=422,
        )

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO evaluations (
                product_id, condition_score, condition_label, criteria_breakdown,
                total_points, assigned_grade, recommended_price,
                final_grade, final_price, rule_version, model_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success')
            """,
            (
                product_id,
                visual.condition_score,
                visual.condition_label,
                json.dumps(calc.criteria_breakdown),
                calc.total_points,
                calc.assigned_grade,
                calc.recommended_price,
                calc.assigned_grade,
                calc.recommended_price,
                calc.rule_version,
                visual.model_version,
            ),
        )
        conn.execute(
            "UPDATE shoes SET process_status = 'pending_review' WHERE product_id = ?",
            (product_id,),
        )
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type="EVALUASI_AI",
            product_id=product_id,
            old_value={"process_status": shoe["process_status"]},
            new_value={
                "condition_score": visual.condition_score,
                "total_points": calc.total_points,
                "assigned_grade": calc.assigned_grade,
                "recommended_price": calc.recommended_price,
                "rule_version": calc.rule_version,
                "model_version": visual.model_version,
                "process_status": "pending_review",
            },
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=evaluated", status_code=303)


@router.post("/admin/shoes/{product_id}/correct")
def correct_evaluation(
    request: Request,
    product_id: int,
    final_grade: str = Form(...),
    final_price: str = Form(...),
    correction_reason: str = Form(...),
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    workspace = _get_shoe_workspace_data(product_id)
    if not workspace or not workspace["evaluation"]:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Belum ada hasil evaluasi untuk dikoreksi.",
            status_code=400,
        )

    cleaned_grade = final_grade.strip().upper()
    cleaned_reason = correction_reason.strip()
    if cleaned_grade not in ALLOWED_GRADES:
        return _render_shoe_detail(request, admin, product_id, flash_error="Pilihan grade tidak valid.", status_code=400)
    if not cleaned_reason:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Alasan koreksi wajib diisi setiap kali admin mengubah grade atau harga (FR-013).",
            status_code=400,
        )
    try:
        parsed_price = float(final_price)
        if parsed_price < 0:
            raise ValueError
    except ValueError:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Harga jual akhir harus berupa angka valid dan tidak negatif.",
            status_code=400,
        )

    ev = workspace["evaluation"]
    with db_session() as conn:
        conn.execute(
            "UPDATE evaluations SET final_grade = ?, final_price = ? WHERE evaluation_id = ?",
            (cleaned_grade, parsed_price, ev["evaluation_id"]),
        )
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type="KOREKSI",
            product_id=product_id,
            old_value={"final_grade": ev["final_grade"], "final_price": ev["final_price"]},
            new_value={"final_grade": cleaned_grade, "final_price": parsed_price},
            correction_reason=cleaned_reason,
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg=corrected", status_code=303)


@router.post("/admin/shoes/{product_id}/decision")
def decide_publication(
    request: Request,
    product_id: int,
    decision: str = Form(...),
    decision_note: str = Form(""),
):
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    workspace = _get_shoe_workspace_data(product_id)
    if not workspace or not workspace["evaluation"]:
        return _render_shoe_detail(
            request,
            admin,
            product_id,
            flash_error="Jalankan evaluasi terlebih dahulu sebelum memutuskan publikasi.",
            status_code=400,
        )

    shoe = workspace["shoe"]
    ev = workspace["evaluation"]
    note = decision_note.strip() or None

    if decision == "approve":
        if ev["final_grade"] == "D":
            new_status = "approved"
            msg_key = "approved_withheld"
        else:
            new_status = "published"
            msg_key = "published"
        action_type = "PERSETUJUAN"
    elif decision == "reject":
        new_status = "rejected"
        msg_key = "rejected"
        action_type = "PENOLAKAN"
    else:
        return _render_shoe_detail(request, admin, product_id, flash_error="Keputusan tidak dikenali.", status_code=400)

    with db_session() as conn:
        conn.execute(
            "UPDATE shoes SET process_status = ? WHERE product_id = ?",
            (new_status, product_id),
        )
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type=action_type,
            product_id=product_id,
            old_value={"process_status": shoe["process_status"]},
            new_value={"process_status": new_status, "final_grade": ev["final_grade"], "final_price": ev["final_price"]},
            correction_reason=note,
        )

    return RedirectResponse(url=f"/admin/shoes/{product_id}?msg={msg_key}", status_code=303)


@router.get("/api/admin/shoes/{product_id}/readiness", response_class=JSONResponse)
def check_shoe_readiness_api(request: Request, product_id: int):
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
