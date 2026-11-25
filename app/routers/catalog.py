import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import APP_NAME, COE_WHATSAPP_NUMBER
from app.database import db_session

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def format_rupiah(value: Optional[float]) -> str:
    if value is None:
        return "Rp 0"
    amount = int(round(float(value)))
    return "Rp " + f"{amount:,}".replace(",", ".")


templates.env.filters["rupiah"] = format_rupiah

router = APIRouter(tags=["Katalog Publik"])

ALLOWED_PUBLIC_GRADES = ("A", "B", "C")
ANGLE_LABELS = {
    "top": "Sisi Atas",
    "right": "Sisi Kanan",
    "left": "Sisi Kiri",
    "bottom": "Sisi Bawah (Sol)",
}
GRADE_DESCRIPTIONS = {
    "A": "Kondisi sangat baik, minim tanda pemakaian, struktur upper dan sol masih prima.",
    "B": "Kondisi baik, terdapat tanda pemakaian ringan yang wajar dan tetap nyaman dipakai.",
    "C": "Kondisi cukup layak pakai dengan tanda pemakaian terlihat jelas, harga lebih ekonomis.",
}
CRITERIA_LABELS = (
    ("condition", "Kondisi Visual (4 Sisi)"),
    ("brand", "Kategori Merek"),
    ("usage_duration", "Estimasi Pemakaian"),
    ("originality", "Bukti Originalitas"),
)


def _calc_savings_pct(price: float, ref_price: float) -> int:
    if not ref_price or ref_price <= 0 or price >= ref_price:
        return 0
    return int(round((1.0 - (float(price) / float(ref_price))) * 100.0))


def _fetch_available_sizes(db_path: Optional[Path] = None) -> list[str]:
    """Ambil daftar ukuran EU unik yang tersedia di katalog publik."""
    query = """
        SELECT DISTINCT TRIM(s.size_eu) AS size_eu
        FROM shoes s
        JOIN evaluations e ON e.evaluation_id = (
            SELECT e2.evaluation_id
            FROM evaluations e2
            WHERE e2.product_id = s.product_id
            ORDER BY e2.created_at DESC, e2.evaluation_id DESC
            LIMIT 1
        )
        WHERE s.process_status = 'published'
          AND e.final_grade != 'D'
          AND e.status = 'success'
          AND TRIM(COALESCE(s.size_eu, '')) != ''
        ORDER BY CAST(TRIM(s.size_eu) AS REAL) ASC, TRIM(s.size_eu) ASC
    """
    with db_session(db_path) as conn:
        rows = conn.execute(query).fetchall()
        return [r["size_eu"] for r in rows]


def _fetch_public_shoes(
    q: str = "",
    grade: str = "",
    size: str = "",
    sort: str = "newest",
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Ambil daftar sepatu publik yang disetujui & bukan Grade D (FR-016, FR-021, BR-009, NFR-011)."""
    conditions = [
        "s.process_status = 'published'",
        "e.final_grade != 'D'",
        "e.status = 'success'",
    ]
    params: list = []

    cleaned_q = q.strip()
    if cleaned_q:
        conditions.append("(LOWER(s.brand) LIKE ? OR LOWER(s.model_name) LIKE ?)")
        like_term = f"%{cleaned_q.lower()}%"
        params.extend([like_term, like_term])

    cleaned_grade = grade.strip().upper()
    if cleaned_grade in ALLOWED_PUBLIC_GRADES:
        conditions.append("e.final_grade = ?")
        params.append(cleaned_grade)

    cleaned_size = size.strip()
    if cleaned_size:
        conditions.append("TRIM(s.size_eu) = ?")
        params.append(cleaned_size)

    order_map = {
        "newest": "s.created_at DESC, s.product_id DESC",
        "price_asc": "e.final_price ASC, s.product_id DESC",
        "price_desc": "e.final_price DESC, s.product_id DESC",
    }
    order_sql = order_map.get(sort, order_map["newest"])

    query = f"""
        SELECT
            s.product_id,
            s.brand,
            s.model_name,
            s.size_eu,
            s.usage_duration,
            s.reference_new_price,
            e.final_grade AS grade,
            e.final_price AS price,
            e.condition_label,
            e.total_points,
            (
                SELECT p.file_path
                FROM shoe_photos p
                WHERE p.product_id = s.product_id AND p.is_valid = 1
                ORDER BY CASE p.angle_type
                    WHEN 'right' THEN 1
                    WHEN 'top' THEN 2
                    WHEN 'left' THEN 3
                    WHEN 'bottom' THEN 4
                    ELSE 5
                END
                LIMIT 1
            ) AS cover_photo,
            (
                SELECT p2.file_path
                FROM shoe_photos p2
                WHERE p2.product_id = s.product_id AND p2.is_valid = 1
                ORDER BY CASE p2.angle_type
                    WHEN 'left' THEN 1
                    WHEN 'top' THEN 2
                    WHEN 'bottom' THEN 3
                    WHEN 'right' THEN 4
                    ELSE 5
                END
                LIMIT 1
            ) AS hover_photo
        FROM shoes s
        JOIN evaluations e ON e.evaluation_id = (
            SELECT e2.evaluation_id
            FROM evaluations e2
            WHERE e2.product_id = s.product_id
            ORDER BY e2.created_at DESC, e2.evaluation_id DESC
            LIMIT 1
        )
        WHERE {' AND '.join(conditions)}
        ORDER BY {order_sql}
    """

    with db_session(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["savings_pct"] = _calc_savings_pct(item["price"], item["reference_new_price"])
            items.append(item)
        return items


def _fetch_public_shoe_detail(
    product_id: int,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    query = """
        SELECT
            s.product_id,
            s.brand,
            s.model_name,
            s.size_eu,
            s.usage_duration,
            s.reference_new_price,
            s.originality_status,
            e.final_grade AS grade,
            e.final_price AS price,
            e.condition_score,
            e.condition_label,
            e.criteria_breakdown,
            e.total_points,
            e.rule_version,
            r.criteria_weights
        FROM shoes s
        JOIN evaluations e ON e.evaluation_id = (
            SELECT e2.evaluation_id
            FROM evaluations e2
            WHERE e2.product_id = s.product_id
            ORDER BY e2.created_at DESC, e2.evaluation_id DESC
            LIMIT 1
        )
        LEFT JOIN system_rules r ON r.version = e.rule_version
        WHERE s.product_id = ?
          AND s.process_status = 'published'
          AND e.final_grade != 'D'
          AND e.status = 'success'
    """
    with db_session(db_path) as conn:
        row = conn.execute(query, (product_id,)).fetchone()
        if not row:
            return None

        photo_rows = conn.execute(
            """
            SELECT angle_type, file_path
            FROM shoe_photos
            WHERE product_id = ? AND is_valid = 1
            ORDER BY CASE angle_type
                WHEN 'right' THEN 1
                WHEN 'left' THEN 2
                WHEN 'top' THEN 3
                WHEN 'bottom' THEN 4
                ELSE 5
            END
            """,
            (product_id,),
        ).fetchall()

        shoe = dict(row)
        shoe["photos"] = [
            {
                "angle_type": p["angle_type"],
                "label": ANGLE_LABELS.get(p["angle_type"], p["angle_type"]),
                "file_path": p["file_path"],
            }
            for p in photo_rows
        ]

        try:
            breakdown = json.loads(shoe.pop("criteria_breakdown") or "{}")
        except json.JSONDecodeError:
            breakdown = {}
        try:
            weights = json.loads(shoe.pop("criteria_weights") or "{}")
        except json.JSONDecodeError:
            weights = {"brand": 25, "condition": 40, "usage_duration": 20, "originality": 15}

        transparency_bars = []
        for key, label in CRITERIA_LABELS:
            max_pts = float(weights.get(key, 25))
            earned = float(breakdown.get(key, 0.0))
            pct = int(round(max(0.0, min(100.0, (earned / max_pts) * 100.0)))) if max_pts > 0 else 0
            transparency_bars.append(
                {
                    "key": key,
                    "label": label,
                    "earned": earned,
                    "max_pts": max_pts,
                    "pct": pct,
                }
            )

        shoe["transparency_bars"] = transparency_bars
        shoe["grade_description"] = GRADE_DESCRIPTIONS.get(shoe["grade"], "")
        shoe["savings_pct"] = _calc_savings_pct(shoe["price"], shoe["reference_new_price"])

        wa_text = (
            f"Halo Admin COE Local Thrift, saya tertarik dengan sepatu "
            f"{shoe['brand']} {shoe['model_name']} (ID #{shoe['product_id']}, "
            f"Ukuran EU {shoe['size_eu'] or '-'}, Grade {shoe['grade']}, "
            f"Harga {format_rupiah(shoe['price'])}). Apakah masih tersedia?"
        )
        shoe["whatsapp_url"] = f"https://wa.me/{COE_WHATSAPP_NUMBER}?text={quote(wa_text)}"
        return shoe


@router.get("/", response_class=HTMLResponse)
@router.get("/catalog", response_class=HTMLResponse)
def catalog_page(
    request: Request,
    q: str = Query(default="", max_length=100),
    grade: str = Query(default="", max_length=5),
    size: str = Query(default="", max_length=20),
    sort: str = Query(default="newest", max_length=20),
):
    shoes = _fetch_public_shoes(q=q, grade=grade, size=size, sort=sort)
    available_sizes = _fetch_available_sizes()

    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context={
            "app_name": APP_NAME,
            "shoes": shoes,
            "available_sizes": available_sizes,
            "q": q.strip(),
            "selected_grade": grade.strip().upper(),
            "selected_size": size.strip(),
            "selected_sort": sort,
            "allowed_grades": ALLOWED_PUBLIC_GRADES,
        },
    )


@router.get("/catalog/{product_id}", response_class=HTMLResponse)
def catalog_detail_page(request: Request, product_id: int):
    shoe = _fetch_public_shoe_detail(product_id)
    if not shoe:
        raise HTTPException(
            status_code=404,
            detail="Sepatu tidak ditemukan atau belum tersedia di katalog publik.",
        )

    return templates.TemplateResponse(
        request=request,
        name="catalog_detail.html",
        context={
            "app_name": APP_NAME,
            "shoe": shoe,
        },
    )


@router.get("/api/catalog", response_class=JSONResponse)
def catalog_api(
    q: str = Query(default="", max_length=100),
    grade: str = Query(default="", max_length=5),
    size: str = Query(default="", max_length=20),
    sort: str = Query(default="newest", max_length=20),
):
    shoes = _fetch_public_shoes(q=q, grade=grade, size=size, sort=sort)
    return {"count": len(shoes), "items": shoes}
