"""Tests for src/conversion.py — unit conversion, currency, Track A + Track B."""

import pytest
from src.database import get_connection, init_db, seed_db
from src.models import ProcessedLineItem
from src.conversion import (
    convert_currency,
    parse_unit_and_quantity,
    convert_to_base_units,
    calculate_cost_per_base_unit,
    process_line_item_conversions,
)


@pytest.fixture
def db_conn():
    """In-memory DB with seed data for testing."""
    import sqlite3
    # Use the real init/seed but on a temp DB
    from src.database import init_db, seed_db, DB_PATH
    import tempfile, os
    from pathlib import Path

    # Create a temp DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("PRAGMA foreign_keys = ON")

    # Manually run schema (can't easily redirect DB_PATH, so inline)
    init_db(conn)
    seed_db(conn)

    yield conn

    conn.close()
    os.unlink(tmp.name)


# --- Currency conversion ---

def test_currency_eur_passthrough(db_conn):
    result = convert_currency(15.00, "EUR", db_conn)
    assert result == 15.00


def test_currency_gbp_conversion(db_conn):
    result = convert_currency(18.50, "GBP", db_conn)
    assert result == pytest.approx(21.645, abs=0.001)


def test_currency_none_amount(db_conn):
    result = convert_currency(None, "EUR", db_conn)
    assert result is None


# --- parse_unit_and_quantity ---

def test_parse_compound_unit_1kg():
    qty, unit = parse_unit_and_quantity("Arabica Blend 1kg", "1kg", 2, "coffee_beans")
    assert qty == 2
    assert unit == "1kg"


def test_parse_compound_unit_500g():
    qty, unit = parse_unit_and_quantity("Decaf Blend 500g", "500g", 1, "coffee_beans")
    assert qty == 1
    assert unit == "500g"


def test_parse_compound_unit_2L():
    qty, unit = parse_unit_and_quantity("Whole Milk 2L", "2L", 5, "whole_milk")
    assert qty == 5
    assert unit == "2L"


def test_parse_compound_unit_2lb():
    qty, unit = parse_unit_and_quantity("Premium Arabica 2lb", "2lb", 1, "coffee_beans")
    assert qty == 1
    assert unit == "2lb"


def test_parse_generic_unit_kg():
    qty, unit = parse_unit_and_quantity("Sugar", "kg", 2, "sugar")
    assert qty == 2
    assert unit == "kg"


def test_parse_each():
    qty, unit = parse_unit_and_quantity("Croissants", "each", 24, "croissant")
    assert qty == 24
    assert unit == "each"


def test_parse_bunch():
    qty, unit = parse_unit_and_quantity("Fresh Mint", "bunch", 3, "fresh_mint")
    assert qty == 3
    assert unit == "bunch"


def test_parse_pack_from_description():
    qty, unit = parse_unit_and_quantity("Napkins (pack of 1000)", "", 1, "napkin")
    assert qty == 1
    assert unit == "pack_1000"


def test_parse_unit_from_description():
    qty, unit = parse_unit_and_quantity("Arabica Blend 1kg", "", 2, "coffee_beans")
    assert qty == 2
    assert unit == "1kg"


# --- convert_to_base_units ---

def test_convert_1kg_to_g(db_conn):
    result, note = convert_to_base_units(2, "1kg", "coffee_beans", db_conn)
    assert result == pytest.approx(2000.0)


def test_convert_500g_to_g(db_conn):
    result, note = convert_to_base_units(1, "500g", "coffee_beans", db_conn)
    assert result == pytest.approx(500.0)


def test_convert_2lb_to_g(db_conn):
    result, note = convert_to_base_units(1, "2lb", "coffee_beans", db_conn)
    assert result == pytest.approx(907.185, abs=0.01)


def test_convert_2L_to_ml(db_conn):
    result, note = convert_to_base_units(5, "2L", "whole_milk", db_conn)
    assert result == pytest.approx(10000.0)


def test_convert_1L_to_ml(db_conn):
    result, note = convert_to_base_units(3, "1L", "oat_milk", db_conn)
    assert result == pytest.approx(3000.0)


def test_convert_bunch_to_leaves(db_conn):
    result, note = convert_to_base_units(3, "bunch", "fresh_mint", db_conn)
    assert result == pytest.approx(60.0)


def test_convert_loaf_to_slice(db_conn):
    result, note = convert_to_base_units(2, "loaf", "bread_loaf", db_conn)
    assert result == pytest.approx(40.0)


def test_convert_each_passthrough(db_conn):
    result, note = convert_to_base_units(24, "each", "croissant", db_conn)
    assert result == 24


def test_missing_conversion_flags(db_conn):
    result, note = convert_to_base_units(1, "gallon", "whole_milk", db_conn)
    assert result is None
    assert "No conversion" in note


# --- calculate_cost_per_base_unit ---

def test_cost_per_base_unit():
    result = calculate_cost_per_base_unit(22.00, 1000.0)
    assert result == pytest.approx(0.022)


def test_cost_per_base_unit_zero_quantity():
    result = calculate_cost_per_base_unit(22.00, 0)
    assert result is None


def test_cost_per_base_unit_none():
    result = calculate_cost_per_base_unit(None, 1000.0)
    assert result is None


# --- Track B: process_line_item_conversions (discrete consumables) ---

def test_discrete_with_pack_size(db_conn):
    item = ProcessedLineItem(
        raw_description="Cups 12oz (pack of 200)",
        quantity=3, line_total=24.00, currency="EUR",
        is_discrete_consumable=True, pack_size=200,
    )
    result = process_line_item_conversions(item, db_conn)
    assert result.total_individual_units == 600
    assert result.base_unit_quantity == 600
    assert result.cost_per_base_unit == pytest.approx(0.04)
    assert result.line_total_eur == 24.00


def test_discrete_no_pack_size_uses_quantity(db_conn):
    """When pack_size is None, quantity IS the individual unit count."""
    item = ProcessedLineItem(
        raw_description="Lids (200 x 0.04)",
        quantity=200, line_total=8.00, currency="EUR",
        is_discrete_consumable=True, pack_size=None,
    )
    result = process_line_item_conversions(item, db_conn)
    assert result.is_flagged is False
    assert result.total_individual_units == 200
    assert result.base_unit_quantity == 200
    assert result.cost_per_base_unit == pytest.approx(0.04, abs=0.001)
    assert result.line_total_eur == 8.00


def test_discrete_currency_conversion(db_conn):
    item = ProcessedLineItem(
        raw_description="Cups 12oz (pack of 100)",
        quantity=2, line_total=15.00, currency="GBP",
        is_discrete_consumable=True, pack_size=100,
    )
    result = process_line_item_conversions(item, db_conn)
    assert result.line_total_eur == pytest.approx(17.55, abs=0.01)
    assert result.total_individual_units == 200
    assert result.cost_per_base_unit == pytest.approx(17.55 / 200, abs=0.001)


# --- Track A: process_line_item_conversions (food ingredients) ---

def test_track_a_coffee_beans(db_conn):
    item = ProcessedLineItem(
        raw_description="Arabica Blend Coffee Beans 1kg",
        quantity=2, raw_unit="1kg", line_total=44.00, currency="EUR",
        canonical_ingredient_id="coffee_beans",
        is_discrete_consumable=False,
    )
    result = process_line_item_conversions(item, db_conn)
    assert result.line_total_eur == 44.00
    assert result.base_unit_quantity == pytest.approx(2000.0)
    assert result.cost_per_base_unit == pytest.approx(0.022)


def test_track_a_gbp_coffee(db_conn):
    item = ProcessedLineItem(
        raw_description="Premium Arabica 2lb",
        quantity=1, raw_unit="2lb", line_total=18.50, currency="GBP",
        canonical_ingredient_id="coffee_beans",
        is_discrete_consumable=False,
    )
    result = process_line_item_conversions(item, db_conn)
    assert result.line_total_eur == pytest.approx(21.645, abs=0.01)
    assert result.base_unit_quantity == pytest.approx(907.185, abs=0.01)
