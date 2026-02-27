"""Tests for src/validation.py — math checks, consistency, status."""

from src.validation import (
    validate_line_math,
    validate_receipt_total,
    validate_corrections,
    validate_category_consistency,
    determine_receipt_status,
)


# --- validate_line_math ---

def test_line_math_correct():
    items = [
        {"item_index": 1, "quantity": 2, "unit_price": 22.00, "line_total": 44.00},
        {"item_index": 2, "quantity": 3, "unit_price": 18.00, "line_total": 54.00},
    ]
    errors = validate_line_math(items)
    assert len(errors) == 0


def test_line_math_discrepancy():
    items = [
        {"item_index": 1, "quantity": 2, "unit_price": 22.00, "line_total": 45.00},
    ]
    errors = validate_line_math(items)
    assert len(errors) == 1
    assert errors[0]["expected"] == 44.00
    assert errors[0]["actual"] == 45.00


def test_line_math_within_tolerance():
    items = [
        {"item_index": 1, "quantity": 3, "unit_price": 1.33, "line_total": 3.99},
    ]
    errors = validate_line_math(items)
    assert len(errors) == 0


def test_line_math_missing_values():
    items = [
        {"item_index": 1, "quantity": None, "unit_price": 22.00, "line_total": 44.00},
    ]
    errors = validate_line_math(items)
    assert len(errors) == 0  # Can't validate without all values


# --- validate_receipt_total ---

def test_receipt_total_matches():
    items = [
        {"line_total": 44.00},
        {"line_total": 54.00},
        {"line_total": 14.00},
    ]
    result = validate_receipt_total(items, 112.00)
    assert result["matches"] is True
    assert result["calculated_sum"] == 112.00


def test_receipt_total_none():
    items = [{"line_total": 44.00}]
    result = validate_receipt_total(items, None)
    assert result["matches"] is True
    assert result["receipt_total"] is None


def test_receipt_total_mismatch():
    items = [
        {"line_total": 44.00},
        {"line_total": 54.00},
    ]
    result = validate_receipt_total(items, 100.00)
    assert result["matches"] is False
    assert result["discrepancy"] == 2.00


# --- validate_corrections ---

def test_corrections_consistent():
    items = [
        {
            "item_index": 1,
            "quantity": 8,
            "unit_price": 1.80,
            "line_total": 14.40,
            "original_unit_price": 2.00,
            "original_line_total": 16.00,
            "correction_note": "Price corrected",
        }
    ]
    results = validate_corrections(items)
    assert len(results) == 1
    assert results[0]["corrected_consistent"] is True
    assert results[0]["original_consistent"] is True


def test_corrections_inconsistent():
    items = [
        {
            "item_index": 1,
            "quantity": 8,
            "unit_price": 1.80,
            "line_total": 15.00,  # Wrong: 8 * 1.80 = 14.40
            "original_unit_price": 2.00,
            "original_line_total": 16.00,
            "correction_note": "Price corrected",
        }
    ]
    results = validate_corrections(items)
    assert len(results) == 1
    assert results[0]["corrected_consistent"] is False


# --- validate_category_consistency ---

def test_category_consistency_valid():
    items = [
        {"line_item_index": 1, "expense_category": "menu_ingredient",
         "selected_ingredient_id": "coffee_beans", "raw_description": "test"},
        {"line_item_index": 2, "expense_category": "operational_food",
         "selected_ingredient_id": None, "raw_description": "cream"},
    ]
    violations = validate_category_consistency(items)
    assert len(violations) == 0


def test_category_consistency_violation():
    items = [
        {"line_item_index": 1, "expense_category": "menu_ingredient",
         "selected_ingredient_id": None, "raw_description": "test"},
    ]
    violations = validate_category_consistency(items)
    assert len(violations) == 1
    assert violations[0]["violation"] == "menu_item_missing_ingredient"


def test_category_consistency_non_menu_with_ingredient():
    items = [
        {"line_item_index": 1, "expense_category": "operational_food",
         "selected_ingredient_id": "coffee_beans", "raw_description": "test"},
    ]
    violations = validate_category_consistency(items)
    assert len(violations) == 1
    assert violations[0]["violation"] == "non_menu_has_ingredient"


# --- determine_receipt_status ---

def test_status_complete():
    status = determine_receipt_status(
        line_math_errors=[],
        total_match={"matches": True},
        pass1_quality="good",
        extraction_count=3,
    )
    assert status == "complete"


def test_status_partial_total_mismatch():
    status = determine_receipt_status(
        line_math_errors=[],
        total_match={"matches": False},
        pass1_quality="good",
        extraction_count=3,
    )
    assert status == "partial"


def test_status_partial_math_errors():
    status = determine_receipt_status(
        line_math_errors=[{"line_index": 1}],
        total_match={"matches": True},
        pass1_quality="good",
        extraction_count=3,
    )
    assert status == "partial"


def test_status_partial_poor_quality():
    status = determine_receipt_status(
        line_math_errors=[],
        total_match={"matches": True},
        pass1_quality="poor",
        extraction_count=3,
    )
    assert status == "partial"


def test_status_failed_unreadable():
    status = determine_receipt_status(
        line_math_errors=[],
        total_match={"matches": True},
        pass1_quality="unreadable",
        extraction_count=0,
    )
    assert status == "failed"


def test_status_failed_no_items():
    status = determine_receipt_status(
        line_math_errors=[],
        total_match={"matches": True},
        pass1_quality="good",
        extraction_count=0,
    )
    assert status == "failed"
