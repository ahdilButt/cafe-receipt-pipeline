"""
Conversion module: currency, unit parsing, base unit conversion, cost calculation.

Two-track architecture:
  Track A: Food ingredients (weight/volume conversion via DB lookup)
  Track B: Discrete consumables (pack_size arithmetic — cups, lids, etc.)
"""

import re
import sqlite3
from typing import Optional
from src.models import ProcessedLineItem
from src.database import get_conversion_factor, get_currency_rate

# Pattern to detect pack sizes in descriptions: "pack of 200", "(200)", etc.
PACK_SIZE_PATTERN = re.compile(r'\(pack\s+of\s+(\d+)\)|\((\d+)\)', re.IGNORECASE)

# Known unit patterns: "1kg", "500g", "2L", "1L", "2lb", "250g", etc.
COMPOUND_UNIT_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g|lb|lbs|L|ml)$', re.IGNORECASE)


def convert_currency(amount: Optional[float], currency: str,
                     conn: sqlite3.Connection) -> Optional[float]:
    """Convert amount to EUR. Returns EUR amount or None if amount is None."""
    if amount is None:
        return None
    if currency == "EUR":
        return amount
    rate = get_currency_rate(conn, currency)
    if rate is None:
        return None
    return round(amount * rate, 4)


def parse_unit_and_quantity(raw_description: str, raw_unit: Optional[str],
                            quantity: Optional[float],
                            canonical_ingredient_id: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Parse the raw unit string + description to determine effective quantity and from_unit.

    Returns (effective_quantity, from_unit).
    """
    if quantity is None:
        return None, raw_unit

    # Normalize raw_unit
    unit = (raw_unit or "").strip()

    # Check if the unit is a compound unit like "1kg", "500g", "2L", "2lb"
    match = COMPOUND_UNIT_PATTERN.match(unit)
    if match:
        # Unit like "1kg", "500g", "2lb" — this IS the from_unit for DB lookup
        # The quantity from the receipt is the number of these packages
        return quantity, unit

    # Check if description contains pack size
    pack_match = PACK_SIZE_PATTERN.search(raw_description)
    if pack_match:
        pack_size = int(pack_match.group(1) or pack_match.group(2))
        return quantity, f"pack_{pack_size}"

    # Standard unit mappings
    unit_lower = unit.lower()

    # Handle "kg", "g", "lb", "lbs", "L", "ml" as generic units
    generic_units = {"kg", "g", "lb", "lbs", "l", "ml"}
    if unit_lower in generic_units:
        # Normalize: "lbs" -> "lb", "l" -> "L"
        normalized = unit_lower
        if normalized == "lbs":
            normalized = "lb"
        if normalized == "l":
            normalized = "L"
        return quantity, normalized

    # "bunch", "loaf", "slice", "leaves" — pass through directly
    # Also handle common foreign equivalents: "mazzo" (Italian for bunch)
    if unit_lower in {"bunch", "mazzo"}:
        return quantity, "bunch"
    if unit_lower in {"loaf", "slice", "leaves"}:
        return quantity, unit_lower

    # "each" — check if the description has weight/volume info that the LLM missed
    if unit_lower == "each":
        desc_match = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|lb|lbs|L|ml)\b', raw_description, re.IGNORECASE)
        if desc_match and canonical_ingredient_id:
            return quantity, f"{desc_match.group(1)}{desc_match.group(2)}"
        return quantity, unit_lower

    # If unit is empty but description might contain weight info
    if not unit:
        # Try to extract unit from description: "Arabica Blend 1kg", "Whole Milk 2L"
        desc_match = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|lb|lbs|L|ml)\b', raw_description, re.IGNORECASE)
        if desc_match:
            return quantity, f"{desc_match.group(1)}{desc_match.group(2)}"

    # Fallback: return as-is (may cause flagging downstream)
    return quantity, unit if unit else None


def convert_to_base_units(quantity: Optional[float], from_unit: Optional[str],
                          ingredient_id: Optional[str],
                          conn: sqlite3.Connection) -> tuple[Optional[float], Optional[str]]:
    """Convert quantity + unit to base unit quantity.
    Returns (base_unit_quantity, conversion_note)."""
    if quantity is None or from_unit is None:
        return None, "Missing quantity or unit"

    # Items measured in "each" — no conversion needed
    if from_unit.lower() in {"each"}:
        return quantity, None

    # Try ingredient-specific conversion first, then generic
    # For compound units like "1kg", "500g", "2L", "2lb"
    factor = get_conversion_factor(conn, ingredient_id, from_unit, _guess_base_unit(from_unit))
    if factor is not None:
        return round(quantity * factor, 4), f"{from_unit} x {factor} = {round(quantity * factor, 4)}"

    # Try generic unit (e.g., "kg" -> "g")
    generic_from = _extract_generic_unit(from_unit)
    if generic_from and generic_from != from_unit:
        base_unit = _guess_base_unit(generic_from)

        # If the generic unit IS the base unit (e.g., "500g" -> generic "g", base "g"),
        # just apply the multiplier directly — no DB lookup needed
        if generic_from == base_unit:
            multiplier = _extract_multiplier(from_unit)
            total = quantity * multiplier
            return round(total, 4), f"{quantity} x {from_unit} = {round(total, 4)} {base_unit}"

        factor = get_conversion_factor(conn, None, generic_from, base_unit)
        if factor is not None:
            # For compound units like "2lb", extract multiplier
            multiplier = _extract_multiplier(from_unit)
            total = quantity * multiplier * factor
            return round(total, 4), f"{quantity} x {from_unit} -> {round(total, 4)} {base_unit}"

    # Try with just the generic unit for the ingredient
    if ingredient_id:
        # Fallback: try matching just the base unit type
        generic_from = _extract_generic_unit(from_unit)
        if generic_from:
            base_unit = _guess_base_unit(generic_from)
            if generic_from == base_unit:
                multiplier = _extract_multiplier(from_unit)
                total = quantity * multiplier
                return round(total, 4), f"Generic: {from_unit} = {round(total, 4)} {base_unit}"
            factor = get_conversion_factor(conn, None, generic_from, base_unit)
            if factor is not None:
                multiplier = _extract_multiplier(from_unit)
                total = quantity * multiplier * factor
                return round(total, 4), f"Generic: {from_unit} -> {round(total, 4)}"

    return None, f"No conversion found: {from_unit} for {ingredient_id}"


def _extract_generic_unit(from_unit: str) -> Optional[str]:
    """Extract the generic unit from a compound unit. '2lb' -> 'lb', '1kg' -> 'kg'."""
    match = COMPOUND_UNIT_PATTERN.match(from_unit)
    if match:
        unit = match.group(2).lower()
        if unit == "lbs":
            return "lb"
        if unit == "l":
            return "L"
        return unit
    return from_unit if from_unit else None


def _extract_multiplier(from_unit: str) -> float:
    """Extract numeric multiplier from compound unit. '2lb' -> 2, '500g' -> 500, '1kg' -> 1."""
    match = COMPOUND_UNIT_PATTERN.match(from_unit)
    if match:
        return float(match.group(1))
    return 1.0


def _guess_base_unit(from_unit: str) -> str:
    """Guess the target base unit from a from_unit."""
    unit_lower = from_unit.lower()
    # Check specific units first (before substring checks)
    if unit_lower in {"bunch"}:
        return "leaves"
    if unit_lower in {"loaf"}:
        return "slice"
    if "pack" in unit_lower:
        return "each"
    if "kg" in unit_lower or "lb" in unit_lower:
        return "g"
    # Check for "g" only if it's not part of another word like "bag"
    if unit_lower in {"g"} or unit_lower.endswith("g") and unit_lower not in {"bag"}:
        return "g"
    if "ml" in unit_lower:
        return "ml"
    # Check for "L" (liter) — must be standalone or at end of digits, not substring of "loaf"
    if unit_lower in {"l"} or (unit_lower.endswith("l") and unit_lower[:-1].isdigit()):
        return "ml"
    return "each"


def calculate_cost_per_base_unit(line_total_eur: Optional[float],
                                 base_unit_quantity: Optional[float]) -> Optional[float]:
    """line_total_eur / base_unit_quantity. Returns None if division not possible."""
    if not line_total_eur or not base_unit_quantity or base_unit_quantity == 0:
        return None
    return round(line_total_eur / base_unit_quantity, 6)


def process_line_item_conversions(item: ProcessedLineItem,
                                  conn: sqlite3.Connection) -> ProcessedLineItem:
    """Apply all conversions to a single line item (Track A or Track B)."""
    # Step 1: Currency conversion (both tracks)
    item.line_total_eur = convert_currency(item.line_total, item.currency, conn)

    if item.is_discrete_consumable:
        # === TRACK B: Discrete consumables ===
        if item.pack_size and item.quantity:
            # "3 packs of 200" → 3 × 200 = 600 individual units
            item.total_individual_units = item.quantity * item.pack_size
            item.base_unit_quantity = item.total_individual_units
            item.cost_per_base_unit = calculate_cost_per_base_unit(
                item.line_total_eur, item.total_individual_units
            )
        elif item.quantity and item.quantity > 0:
            # No pack_size but quantity IS the individual unit count
            # e.g., "200 x EUR 0.04" → qty=200 individual lids
            item.total_individual_units = item.quantity
            item.base_unit_quantity = item.quantity
            item.cost_per_base_unit = calculate_cost_per_base_unit(
                item.line_total_eur, item.quantity
            )
        else:
            item.is_flagged = True
            item.flag_reason = "Discrete consumable but quantity unknown"
    else:
        # === TRACK A: Food ingredients (weight/volume) ===
        effective_qty, from_unit = parse_unit_and_quantity(
            item.raw_description, item.raw_unit, item.quantity,
            item.canonical_ingredient_id
        )
        base_qty, note = convert_to_base_units(
            effective_qty, from_unit, item.canonical_ingredient_id, conn
        )
        item.base_unit_quantity = base_qty
        item.conversion_note = note
        if base_qty and item.line_total_eur:
            item.cost_per_base_unit = calculate_cost_per_base_unit(
                item.line_total_eur, base_qty
            )
        if base_qty is None:
            item.is_flagged = True
            item.flag_reason = f"No conversion found: {from_unit} for {item.canonical_ingredient_id}"

    return item
