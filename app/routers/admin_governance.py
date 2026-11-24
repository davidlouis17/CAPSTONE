import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_current_admin
from app.config import APP_NAME
from app.database import db_session
from app.routers.admin import _log_audit, _require_admin_redirect
from app.routers.catalog import format_rupiah

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["rupiah"] = format_rupiah

router = APIRouter(tags=["Audit & Aturan Bisnis"])

ACTION_TYPES = (
    "INPUT_DATA",
    "VERIFIKASI_FISIK",
    "UNGGAH_FOTO",
    "EVALUASI_AI",
    "EVALUASI_GAGAL",
    "KOREKSI",
    "PERSETUJUAN",
    "PENOLAKAN",
    "UBAH_ATURAN",
    "SEED_INITIAL",
)


def _fetch_rules_history() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT rule_id, version, criteria_weights, grade_thresholds,
                   discount_percentage, rounding_unit, is_active, created_at
            FROM system_rules
            ORDER BY version DESC
            """
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["weights"] = json.loads(item["criteria_weights"])
        item["thresholds"] = json.loads(item["grade_thresholds"])
        item["discounts"] = json.loads(item["discount_percentage"])
        result.append(item)
    return result


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_log_page(
    request: Request,
    action_type: str = Query(default="", max_length=50),
    product_id: str = Query(default="", max_length=20),
):
    """Halaman riwayat penilaian, koreksi, dan keputusan audit (FR-018, UI-005, TC-015)."""
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    conditions = ["1=1"]
    params: list = []

    cleaned_action = action_type.strip().upper()
    if cleaned_action:
        conditions.append("l.action_type = ?")
        params.append(cleaned_action)

    cleaned_pid = product_id.strip()
    if cleaned_pid.isdigit():
        conditions.append("l.product_id = ?")
        params.append(int(cleaned_pid))

    query = f"""
        SELECT
            l.log_id,
            l.product_id,
            l.action_type,
            l.old_value,
            l.new_value,
            l.correction_reason,
            l.timestamp,
            a.name AS admin_name,
            a.role AS admin_role,
            s.brand,
            s.model_name
        FROM audit_logs l
        JOIN admins a ON a.admin_id = l.admin_id
        LEFT JOIN shoes s ON s.product_id = l.product_id
        WHERE {' AND '.join(conditions)}
        ORDER BY l.timestamp DESC, l.log_id DESC
        LIMIT 200
    """

    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="admin/audit_logs.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "logs": [dict(r) for r in rows],
            "action_types": ACTION_TYPES,
            "selected_action": cleaned_action,
            "selected_product_id": cleaned_pid,
        },
    )


@router.get("/admin/rules", response_class=HTMLResponse)
def rules_page(request: Request, msg: str = "", err: str = ""):
    """Halaman pengelolaan aturan bobot, batas grade, dan potongan harga (FR-019, NFR-009)."""
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    rules = _fetch_rules_history()
    active_rule = next((r for r in rules if r["is_active"]), rules[0] if rules else None)
    flash_map = {
        "updated": "Versi aturan baru berhasil diaktifkan dan dicatat ke log audit. Riwayat versi lama tetap terjaga.",
    }

    return templates.TemplateResponse(
        request=request,
        name="admin/rules.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "rules": rules,
            "active_rule": active_rule,
            "can_edit": admin["role"] == "management",
            "flash_success": flash_map.get(msg, ""),
            "flash_error": err,
        },
    )


@router.post("/admin/rules", response_class=HTMLResponse)
def update_rules_submit(
    request: Request,
    weight_brand: int = Form(...),
    weight_condition: int = Form(...),
    weight_usage: int = Form(...),
    weight_originality: int = Form(...),
    threshold_a: int = Form(...),
    threshold_b: int = Form(...),
    threshold_c: int = Form(...),
    discount_a: int = Form(...),
    discount_b: int = Form(...),
    discount_c: int = Form(...),
    discount_d: int = Form(...),
    rounding_unit: int = Form(...),
    change_reason: str = Form(...),
):
    """Simpan versi baru aturan bisnis — khusus peran management (FR-019, NFR-002, NFR-009)."""
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    if admin["role"] != "management":
        raise HTTPException(
            status_code=403,
            detail="Hanya peran Manajemen COE yang berwenang mengubah aturan grade dan harga (FR-019).",
        )

    errors: list[str] = []
    total_weight = weight_brand + weight_condition + weight_usage + weight_originality
    if total_weight != 100:
        errors.append(f"Total bobot 4 kriteria harus tepat 100 (saat ini: {total_weight}).")
    if min(weight_brand, weight_condition, weight_usage, weight_originality) <= 0:
        errors.append("Setiap bobot kriteria harus lebih dari 0.")
    if not (100 > threshold_a > threshold_b > threshold_c > 0):
        errors.append("Batas grade harus menurun berurutan: 100 > A > B > C > 0.")
    if any(d < 0 or d > 95 for d in (discount_a, discount_b, discount_c, discount_d)):
        errors.append("Persentase potongan harus berada di rentang 0% hingga 95%.")
    if rounding_unit < 1000:
        errors.append("Kelipatan pembulatan harga minimal Rp 1.000.")
    cleaned_reason = change_reason.strip()
    if not cleaned_reason:
        errors.append("Alasan pembaruan aturan wajib diisi.")

    if errors:
        rules = _fetch_rules_history()
        active_rule = next((r for r in rules if r["is_active"]), rules[0] if rules else None)
        return templates.TemplateResponse(
            request=request,
            name="admin/rules.html",
            context={
                "app_name": APP_NAME,
                "admin": admin,
                "rules": rules,
                "active_rule": active_rule,
                "can_edit": True,
                "flash_success": "",
                "flash_error": " ".join(errors),
            },
            status_code=400,
        )

    new_weights = {
        "brand": weight_brand,
        "condition": weight_condition,
        "usage_duration": weight_usage,
        "originality": weight_originality,
    }
    new_thresholds = {"A": threshold_a, "B": threshold_b, "C": threshold_c, "D": 0}
    new_discounts = {"A": discount_a, "B": discount_b, "C": discount_c, "D": discount_d}

    with db_session() as conn:
        prev = conn.execute(
            "SELECT version, criteria_weights, grade_thresholds, discount_percentage, rounding_unit FROM system_rules WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
        ).fetchone()
        max_ver = conn.execute("SELECT COALESCE(MAX(version), 0) AS mv FROM system_rules").fetchone()["mv"]
        next_ver = int(max_ver) + 1

        conn.execute("UPDATE system_rules SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            """
            INSERT INTO system_rules
                (version, criteria_weights, grade_thresholds, discount_percentage, rounding_unit, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                next_ver,
                json.dumps(new_weights),
                json.dumps(new_thresholds),
                json.dumps(new_discounts),
                rounding_unit,
            ),
        )
        _log_audit(
            conn,
            admin_id=admin["admin_id"],
            action_type="UBAH_ATURAN",
            product_id=None,
            old_value={"version": prev["version"]} if prev else None,
            new_value={
                "version": next_ver,
                "weights": new_weights,
                "thresholds": new_thresholds,
                "discounts": new_discounts,
                "rounding_unit": rounding_unit,
            },
            correction_reason=cleaned_reason,
        )

    return RedirectResponse(url="/admin/rules?msg=updated", status_code=303)
