import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import get_current_admin
from app.config import APP_NAME
from app.database import db_session
from app.routers.admin import _log_audit, _require_admin_redirect
from app.routers.catalog import format_rupiah

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["rupiah"] = format_rupiah

WIB_TZ = timezone(timedelta(hours=7))
MONTH_ID = (
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
)


def format_wib(raw_ts: Optional[str]) -> str:
    """Konversi timestamp UTC SQLite ('YYYY-MM-DD HH:MM:SS') ke format lokal WIB."""
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


templates.env.filters["wib"] = format_wib

router = APIRouter(tags=["Audit, Aturan & Ekspor"])

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


@router.get("/admin/export/shoes.csv")
def export_shoes_csv(request: Request):
    guard = _require_admin_redirect(request)
    if guard:
        return guard

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                s.product_id,
                s.brand,
                s.model_name,
                s.size_eu,
                s.usage_duration,
                s.purchase_price,
                s.reference_new_price,
                s.originality_status,
                s.physical_verified,
                s.process_status,
                e.condition_score,
                e.total_points,
                e.assigned_grade,
                e.final_grade,
                e.recommended_price,
                e.final_price,
                s.created_at
            FROM shoes s
            LEFT JOIN evaluations e ON e.evaluation_id = (
                SELECT e2.evaluation_id
                FROM evaluations e2
                WHERE e2.product_id = s.product_id
                ORDER BY e2.created_at DESC, e2.evaluation_id DESC
                LIMIT 1
            )
            ORDER BY s.product_id ASC
            """
        ).fetchall()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "product_id", "brand", "model_name", "size_eu", "usage_duration",
        "purchase_price", "reference_new_price", "originality_status",
        "physical_verified", "process_status", "condition_score", "total_points",
        "assigned_grade", "final_grade", "recommended_price", "final_price", "created_at_wib",
    ])
    for r in rows:
        row_vals = [r[col] for col in r.keys()[:-1]]
        row_vals.append(format_wib(r["created_at"]))
        writer.writerow(row_vals)

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="local_thrift_shoes.csv"'},
    )


@router.get("/admin/export/audit.csv")
def export_audit_csv(request: Request):
    guard = _require_admin_redirect(request)
    if guard:
        return guard

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                l.log_id,
                l.timestamp,
                a.name AS admin_name,
                a.role AS admin_role,
                l.product_id,
                s.brand,
                l.action_type,
                l.old_value,
                l.new_value,
                l.correction_reason
            FROM audit_logs l
            JOIN admins a ON a.admin_id = l.admin_id
            LEFT JOIN shoes s ON s.product_id = l.product_id
            ORDER BY l.timestamp DESC, l.log_id DESC
            """
        ).fetchall()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "log_id", "timestamp", "admin_name", "admin_role", "product_id",
        "brand", "action_type", "old_value", "new_value", "correction_reason",
    ])
    for r in rows:
        writer.writerow([
            r["log_id"],
            format_wib(r["timestamp"]),
            r["admin_name"],
            r["admin_role"],
            r["product_id"],
            r["brand"],
            r["action_type"],
            r["old_value"],
            r["new_value"],
            r["correction_reason"],
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="local_thrift_audit_logs.csv"'},
    )


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_log_page(
    request: Request,
    action_type: str = Query(default="", max_length=50),
    product_id: str = Query(default="", max_length=20),
):
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
            "SELECT version FROM system_rules WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
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


@router.get("/admin/shoes/{product_id}/label", response_class=HTMLResponse)
def shoe_label_page(request: Request, product_id: int):
    """Halaman cetak Hang Tag / Label Sepatu + QR Code ke /catalog/{id}."""
    guard = _require_admin_redirect(request)
    if guard:
        return guard
    admin = get_current_admin(request)

    with db_session() as conn:
        shoe_row = conn.execute(
            """
            SELECT
                s.product_id,
                s.brand,
                s.model_name,
                s.size_eu,
                s.usage_duration,
                s.reference_new_price,
                s.process_status,
                e.final_grade,
                e.final_price,
                e.total_points,
                e.condition_label,
                e.rule_version
            FROM shoes s
            LEFT JOIN evaluations e ON e.evaluation_id = (
                SELECT e2.evaluation_id
                FROM evaluations e2
                WHERE e2.product_id = s.product_id
                ORDER BY e2.created_at DESC, e2.evaluation_id DESC
                LIMIT 1
            )
            WHERE s.product_id = ?
            """,
            (product_id,),
        ).fetchone()

    if not shoe_row:
        raise HTTPException(status_code=404, detail="Data sepatu tidak ditemukan.")

    shoe = dict(shoe_row)
    base_url = str(request.base_url).rstrip("/")
    catalog_url = f"{base_url}/catalog/{product_id}"

    return templates.TemplateResponse(
        request=request,
        name="admin/shoe_label.html",
        context={
            "app_name": APP_NAME,
            "admin": admin,
            "shoe": shoe,
            "catalog_url": catalog_url,
        },
    )
