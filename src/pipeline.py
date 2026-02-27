"""
Pipeline orchestration — per-receipt processing.

Handles the full 3-pass pipeline: recon -> extract -> categorise,
plus validation, conversion, and DB storage.
"""

import base64
import json
import sqlite3
import traceback
import anthropic
from pathlib import Path
from typing import Optional

from src.models import (
    ProcessedReceipt, ProcessedLineItem, ExpenseCategory,
    Pass1Result, Pass2Result, Pass3Result,
)
from src.pass1_recon import run_pass1
from src.pass2_extract import run_pass2
from src.pass3_categorise import run_pass3
from src.validation import (
    validate_line_math, validate_receipt_total,
    validate_corrections, validate_category_consistency,
    determine_receipt_status,
)
from src.conversion import process_line_item_conversions, convert_currency
from src.database import (
    get_supplier_by_name, insert_receipt,
    insert_processing_log, get_currency_rate,
)


def load_image_as_base64(image_path: Path) -> str:
    """Read JPEG file, return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def generate_receipt_id(filename: str) -> str:
    """Generate receipt_id using filename stem (e.g., R001)."""
    return Path(filename).stem


def process_single_receipt(client: anthropic.Anthropic,
                           conn: sqlite3.Connection,
                           image_path: Path,
                           supplier_list: list[dict],
                           canonical_ingredients: list[dict],
                           menu_data: dict) -> ProcessedReceipt:
    """Full 3-pass pipeline for one receipt."""
    filename = image_path.name
    receipt_id = generate_receipt_id(filename)

    receipt = ProcessedReceipt(
        receipt_id=receipt_id,
        filename=filename,
    )

    # Insert a minimal receipt row so processing_log FK is satisfied
    insert_receipt(conn, receipt)

    # --- Pass 1: Recon (Vision) ---
    try:
        image_b64 = load_image_as_base64(image_path)
        p1 = run_pass1(client, image_b64, supplier_list)

        receipt.supplier_name = p1.supplier_name
        receipt.date = p1.date
        receipt.currency = p1.currency
        receipt.image_quality = p1.image_quality.value if hasattr(p1.image_quality, 'value') else str(p1.image_quality)
        receipt.damage_type = p1.damage_type.value if hasattr(p1.damage_type, 'value') else str(p1.damage_type)
        receipt.invoice_number = p1.invoice_number
        receipt.pass1_reasoning = p1.reasoning

        # Supplier lookup
        supplier = get_supplier_by_name(conn, p1.supplier_name)
        if supplier:
            receipt.supplier_id = supplier["supplier_id"]

        insert_processing_log(conn, receipt_id, "pass1", "info",
                              f"Supplier: {p1.supplier_name}, Quality: {p1.image_quality}, Format: {p1.format_type}")

    except Exception as e:
        receipt.status = "failed"
        receipt.notes = f"Pass 1 failed: {str(e)}"
        insert_processing_log(conn, receipt_id, "pass1", "error",
                              f"Pass 1 failed: {str(e)}", traceback.format_exc())
        insert_receipt(conn, receipt)
        return receipt

    # --- Pass 2: Extract (Vision) ---
    try:
        supplier_profile = supplier if supplier else {}
        p2 = run_pass2(client, image_b64, supplier_profile, p1)

        receipt.receipt_total = p2.receipt_total
        receipt.pass2_reasoning = p2.reasoning

        insert_processing_log(conn, receipt_id, "pass2", "info",
                              f"Extracted {len(p2.line_items)} line items, total={p2.receipt_total}")

    except Exception as e:
        receipt.status = "failed"
        receipt.notes = f"Pass 2 failed: {str(e)}"
        insert_processing_log(conn, receipt_id, "pass2", "error",
                              f"Pass 2 failed: {str(e)}", traceback.format_exc())
        insert_receipt(conn, receipt)
        return receipt

    # --- Validation (Code) ---
    line_items_dicts = [item.model_dump() for item in p2.line_items]
    line_math_errors = validate_line_math(line_items_dicts)
    total_match = validate_receipt_total(line_items_dicts, p2.receipt_total)
    corrections = validate_corrections(line_items_dicts)

    if line_math_errors:
        insert_processing_log(conn, receipt_id, "validation", "warning",
                              f"Line math errors: {len(line_math_errors)}")
    if not total_match.get("matches", True):
        insert_processing_log(conn, receipt_id, "validation", "warning",
                              f"Total mismatch: calculated={total_match['calculated_sum']}, receipt={total_match['receipt_total']}")
    if corrections:
        receipt.has_corrections = True
        insert_processing_log(conn, receipt_id, "validation", "info",
                              f"Corrections detected on {len(corrections)} items")

    # --- Pass 3: Categorise (Text) ---
    try:
        # Add receipt_id to supplier profile for prompt
        profile_with_id = dict(supplier_profile) if supplier_profile else {}
        profile_with_id["_receipt_id"] = receipt_id

        p3 = run_pass3(client, line_items_dicts, profile_with_id,
                        canonical_ingredients, menu_data)

        receipt.pass3_reasoning = p3.reasoning

        insert_processing_log(conn, receipt_id, "pass3", "info",
                              f"Categorised {len(p3.categorised_items)} items")

    except Exception as e:
        # Pass 3 fails -> status='partial', store Pass 1+2 data
        receipt.status = "partial"
        receipt.notes = f"Pass 3 failed: {str(e)}"
        insert_processing_log(conn, receipt_id, "pass3", "error",
                              f"Pass 3 failed: {str(e)}", traceback.format_exc())

        # Still store line items from Pass 2 without categorisation
        for p2_item in p2.line_items:
            li = ProcessedLineItem(
                raw_description=p2_item.raw_description,
                quantity=p2_item.quantity,
                raw_unit=p2_item.raw_unit,
                unit_price=p2_item.unit_price,
                line_total=p2_item.line_total,
                currency=receipt.currency,
                original_unit_price=p2_item.original_unit_price,
                original_line_total=p2_item.original_line_total,
                correction_note=p2_item.correction_note,
                pack_size=p2_item.pack_size,
            )
            receipt.line_items.append(li)

        insert_receipt(conn, receipt)
        return receipt

    # --- Category Validation (Code) ---
    p3_items_dicts = [item.model_dump() for item in p3.categorised_items]
    cat_violations = validate_category_consistency(p3_items_dicts)
    if cat_violations:
        insert_processing_log(conn, receipt_id, "validation", "warning",
                              f"Category consistency violations: {len(cat_violations)}")

    # --- Merge Pass2 + Pass3 -> ProcessedLineItem list ---
    # Build lookup from Pass 3 by line_item_index
    p3_lookup = {item.line_item_index: item for item in p3.categorised_items}

    for p2_item in p2.line_items:
        p3_item = p3_lookup.get(p2_item.item_index)

        li = ProcessedLineItem(
            raw_description=p2_item.raw_description,
            quantity=p2_item.quantity,
            raw_unit=p2_item.raw_unit,
            unit_price=p2_item.unit_price,
            line_total=p2_item.line_total,
            currency=receipt.currency,
            original_unit_price=p2_item.original_unit_price,
            original_line_total=p2_item.original_line_total,
            correction_note=p2_item.correction_note,
            pack_size=p2_item.pack_size,
        )

        if p3_item:
            li.canonical_ingredient_id = p3_item.selected_ingredient_id
            li.expense_category = p3_item.expense_category
            li.category_reasoning = p3_item.reasoning
            li.match_confidence = p3_item.confidence
            li.match_reasoning = p3_item.reasoning
            li.is_discrete_consumable = p3_item.is_discrete_consumable

        receipt.line_items.append(li)

    # --- Conversion (Code) — Track A or Track B per item ---
    for li in receipt.line_items:
        try:
            process_line_item_conversions(li, conn)
        except Exception as e:
            li.is_flagged = True
            li.flag_reason = f"Conversion error: {str(e)}"
            insert_processing_log(conn, receipt_id, "conversion", "error",
                                  f"Conversion error for '{li.raw_description}': {str(e)}")

    # --- Convert receipt total to EUR ---
    receipt.receipt_total_eur = convert_currency(receipt.receipt_total, receipt.currency, conn)

    # --- Determine final status ---
    quality = receipt.image_quality or "good"
    receipt.status = determine_receipt_status(
        line_math_errors, total_match, quality, len(receipt.line_items)
    )

    # --- Store to DB ---
    insert_receipt(conn, receipt)

    return receipt
