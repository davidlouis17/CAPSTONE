from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Optional

from app.database import db_session

TIER1_BRANDS = {
    "nike", "adidas", "new balance", "asics", "jordan",
    "air jordan", "salomon", "on", "hoka", "saucony", "mizuno",
}
TIER2_BRANDS = {
    "puma", "converse", "vans", "reebok", "skechers",
    "compass", "ventela", "ortuseight", "specs", "brodo", "fila",
}

USAGE_RATIO_MAP = {
    "< 6 bulan": 0.95,
    "6 - 12 bulan": 0.75,
    "1 - 2 tahun": 0.55,
    "> 2 tahun": 0.30,
}

ORIGINALITY_RATIO_MAP = {
    "struk_dan_box": 1.00,
    "barcode_terverifikasi": 0.80,
    "box_saja": 0.55,
    "tanpa_bukti": 0.20,
}


@dataclass
class RuleCalculationResult:
    criteria_breakdown: Dict[str, float]
    total_points: float
    assigned_grade: str
    discount_pct: float
    recommended_price: float
    rule_version: int


def get_active_rule(db_path: Optional[Path] = None) -> dict:
    """Ambil snapshot aturan sistem aktif dari database (FR-019, BR-004)."""
    with db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT rule_id, version, criteria_weights, grade_thresholds,
                   discount_percentage, rounding_unit, is_active
            FROM system_rules
            WHERE is_active = 1
            ORDER BY version DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("Aturan sistem aktif tidak ditemukan di tabel system_rules.")
    return {
        "rule_id": row["rule_id"],
        "version": row["version"],
        "criteria_weights": json.loads(row["criteria_weights"]),
        "grade_thresholds": json.loads(row["grade_thresholds"]),
        "discount_percentage": json.loads(row["discount_percentage"]),
        "rounding_unit": int(row["rounding_unit"]),
    }


def _brand_ratio(brand: str) -> float:
    normalized = brand.strip().lower()
    if normalized in TIER1_BRANDS:
        return 0.92
    if normalized in TIER2_BRANDS:
        return 0.78
    return 0.65


def calculate_grade_and_price(
    brand: str,
    condition_score: float,
    usage_duration: str,
    originality_status: str,
    reference_new_price: float,
    rule: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> RuleCalculationResult:
    """
    Mesin aturan deterministik 4 kriteria (FR-009, FR-010, FR-011, BR-003 s.d. BR-006).
    Terpisah penuh dari model ML agar hasil grade dan harga dapat ditelusuri.
    """
    active_rule = rule or get_active_rule(db_path)
    weights = active_rule["criteria_weights"]
    thresholds = active_rule["grade_thresholds"]
    discounts = active_rule["discount_percentage"]
    rounding_unit = max(1, int(active_rule.get("rounding_unit", 5000)))

    clamped_condition = max(0.0, min(100.0, float(condition_score)))
    brand_pts = round(_brand_ratio(brand) * float(weights["brand"]), 2)
    condition_pts = round((clamped_condition / 100.0) * float(weights["condition"]), 2)
    usage_pts = round(USAGE_RATIO_MAP.get(usage_duration, 0.50) * float(weights["usage_duration"]), 2)
    orig_pts = round(ORIGINALITY_RATIO_MAP.get(originality_status, 0.20) * float(weights["originality"]), 2)

    total_points = round(brand_pts + condition_pts + usage_pts + orig_pts, 2)

    if total_points >= float(thresholds["A"]):
        grade = "A"
    elif total_points >= float(thresholds["B"]):
        grade = "B"
    elif total_points >= float(thresholds["C"]):
        grade = "C"
    else:
        grade = "D"

    discount_pct = float(discounts[grade])
    raw_price = float(reference_new_price) * (1.0 - discount_pct / 100.0)
    rounded_price = round(raw_price / rounding_unit) * rounding_unit
    recommended_price = float(max(0.0, rounded_price))

    return RuleCalculationResult(
        criteria_breakdown={
            "brand": brand_pts,
            "condition": condition_pts,
            "usage_duration": usage_pts,
            "originality": orig_pts,
        },
        total_points=total_points,
        assigned_grade=grade,
        discount_pct=discount_pct,
        recommended_price=recommended_price,
        rule_version=int(active_rule["version"]),
    )
