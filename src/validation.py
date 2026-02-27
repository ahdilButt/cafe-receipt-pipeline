"""
Validation module: math checks, consistency verification, receipt status.

All pure code — no LLM calls. Fully unit testable.
"""

from typing import Optional

MATH_TOLERANCE_EUR = 0.02


def validate_line_math(line_items: list[dict]) -> list[dict]:
    """Check qty x unit_price ~ line_total for each item.
    Returns list of {line_index, expected, actual, discrepancy} for failures."""
    errors = []
    for item in line_items:
        qty = item.get("quantity")
        price = item.get("unit_price")
        total = item.get("line_total")
        if qty is not None and price is not None and total is not None:
            expected = qty * price
            if abs(expected - total) > MATH_TOLERANCE_EUR:
                errors.append({
                    "line_index": item.get("item_index", 0),
                    "expected": round(expected, 2),
                    "actual": total,
                    "discrepancy": round(abs(expected - total), 2),
                })
    return errors


def validate_receipt_total(line_items: list[dict],
                           receipt_total: Optional[float]) -> dict:
    """Check sum(line_totals) ~ receipt_total.
    Returns {calculated_sum, receipt_total, matches, discrepancy}."""
    calculated_sum = sum(
        item.get("line_total", 0) for item in line_items
        if item.get("line_total") is not None
    )
    calculated_sum = round(calculated_sum, 2)

    if receipt_total is None:
        return {
            "calculated_sum": calculated_sum,
            "receipt_total": None,
            "matches": True,  # Can't fail if total is unknown
            "discrepancy": None,
            "note": "Receipt total not available (damaged/torn)",
        }

    discrepancy = round(abs(calculated_sum - receipt_total), 2)
    matches = discrepancy <= MATH_TOLERANCE_EUR

    result = {
        "calculated_sum": calculated_sum,
        "receipt_total": receipt_total,
        "matches": matches,
        "discrepancy": discrepancy,
    }
    if not matches:
        result["note"] = f"Lines sum to {calculated_sum}, receipt shows {receipt_total}"
    return result


def validate_corrections(line_items: list[dict]) -> list[dict]:
    """For items with corrections: verify both original and corrected sets
    are internally consistent. Returns list of verification results."""
    results = []
    for item in line_items:
        if item.get("correction_note") or item.get("original_unit_price") is not None:
            qty = item.get("quantity")
            result = {
                "line_index": item.get("item_index", 0),
                "has_correction": True,
                "corrected_consistent": True,
                "original_consistent": True,
            }

            # Check corrected values
            if qty and item.get("unit_price") and item.get("line_total"):
                expected = qty * item["unit_price"]
                if abs(expected - item["line_total"]) > MATH_TOLERANCE_EUR:
                    result["corrected_consistent"] = False

            # Check original values
            if qty and item.get("original_unit_price") and item.get("original_line_total"):
                expected = qty * item["original_unit_price"]
                if abs(expected - item["original_line_total"]) > MATH_TOLERANCE_EUR:
                    result["original_consistent"] = False

            results.append(result)
    return results


def validate_category_consistency(pass3_items: list[dict]) -> list[dict]:
    """Verify:
    - menu_ingredient/menu_consumable items MUST have canonical_ingredient_id
    - operational/non_operational items should NOT have canonical_ingredient_id
    Returns list of violations."""
    violations = []
    menu_categories = {"menu_ingredient", "menu_consumable"}
    non_menu_categories = {"operational_food", "operational_supply",
                           "equipment_service", "non_operational"}

    for item in pass3_items:
        category = item.get("expense_category", "unknown")
        ingredient_id = item.get("selected_ingredient_id")

        if category in menu_categories and not ingredient_id:
            violations.append({
                "line_index": item.get("line_item_index", 0),
                "violation": "menu_item_missing_ingredient",
                "message": f"{category} item has no canonical_ingredient_id",
                "raw_description": item.get("raw_description", ""),
            })

        if category in non_menu_categories and ingredient_id:
            violations.append({
                "line_index": item.get("line_item_index", 0),
                "violation": "non_menu_has_ingredient",
                "message": f"{category} item has canonical_ingredient_id={ingredient_id}",
                "raw_description": item.get("raw_description", ""),
            })

    return violations


def determine_receipt_status(line_math_errors: list, total_match: dict,
                             pass1_quality: str, extraction_count: int) -> str:
    """Return 'complete', 'partial', or 'failed' based on validation results.
    - failed: image_quality == 'unreadable' or extraction_count == 0
    - partial: total mismatch, line math errors, or image_quality == 'poor'
    - complete: all checks pass"""
    if pass1_quality == "unreadable" or extraction_count == 0:
        return "failed"

    if (not total_match.get("matches", True) or
            line_math_errors or
            pass1_quality == "poor"):
        return "partial"

    return "complete"
