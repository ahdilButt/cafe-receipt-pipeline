"""Tests for src/aggregation.py — weighted averages, COGS, margins."""

import json
import pytest
import sqlite3
import tempfile
import os

from src.database import init_db, seed_db
from src.aggregation import (
    calculate_ingredient_costs,
    calculate_menu_item_costs,
    calculate_expense_summary,
)


@pytest.fixture
def db_with_data():
    """DB with seed data and some test line items."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    seed_db(conn)

    # Insert test receipts
    conn.execute("""
        INSERT INTO receipts (receipt_id, filename, supplier_id, status, currency)
        VALUES ('TEST001', 'TEST001.jpg', 1, 'complete', 'EUR')
    """)
    conn.execute("""
        INSERT INTO receipts (receipt_id, filename, supplier_id, status, currency)
        VALUES ('TEST002', 'TEST002.jpg', 4, 'complete', 'EUR')
    """)

    # Insert test line items with known values
    # Coffee beans: 2 purchases, different prices
    conn.execute("""
        INSERT INTO line_items (receipt_id, raw_description, quantity, raw_unit,
            unit_price, line_total, currency, canonical_ingredient_id,
            expense_category, line_total_eur, base_unit_quantity, cost_per_base_unit)
        VALUES ('TEST001', 'Arabica 1kg', 2, '1kg', 22.00, 44.00, 'EUR',
            'coffee_beans', 'menu_ingredient', 44.00, 2000.0, 0.022)
    """)
    conn.execute("""
        INSERT INTO line_items (receipt_id, raw_description, quantity, raw_unit,
            unit_price, line_total, currency, canonical_ingredient_id,
            expense_category, line_total_eur, base_unit_quantity, cost_per_base_unit)
        VALUES ('TEST001', 'House Blend 1kg', 3, '1kg', 18.00, 54.00, 'EUR',
            'coffee_beans', 'menu_ingredient', 54.00, 3000.0, 0.018)
    """)

    # Whole milk
    conn.execute("""
        INSERT INTO line_items (receipt_id, raw_description, quantity, raw_unit,
            unit_price, line_total, currency, canonical_ingredient_id,
            expense_category, line_total_eur, base_unit_quantity, cost_per_base_unit)
        VALUES ('TEST002', 'Whole Milk 2L', 5, '2L', 2.80, 14.00, 'EUR',
            'whole_milk', 'menu_ingredient', 14.00, 10000.0, 0.0014)
    """)

    # Napkin (discrete consumable)
    conn.execute("""
        INSERT INTO line_items (receipt_id, raw_description, quantity, raw_unit,
            unit_price, line_total, currency, canonical_ingredient_id,
            expense_category, line_total_eur, base_unit_quantity, cost_per_base_unit,
            is_discrete_consumable, pack_size, total_individual_units)
        VALUES ('TEST002', 'Napkins (pack of 1000)', 1, 'pack', 15.00, 15.00, 'EUR',
            'napkin', 'menu_consumable', 15.00, 1000.0, 0.015,
            1, 1000, 1000.0)
    """)

    # Operational food (not in menu)
    conn.execute("""
        INSERT INTO line_items (receipt_id, raw_description, quantity, raw_unit,
            unit_price, line_total, currency,
            expense_category, line_total_eur)
        VALUES ('TEST002', 'Butter 250g', 3, '250g', 2.50, 7.50, 'EUR',
            'operational_food', 7.50)
    """)

    conn.commit()
    yield conn

    conn.close()
    os.unlink(tmp.name)


def test_ingredient_costs_weighted_average(db_with_data):
    results = calculate_ingredient_costs(db_with_data)

    coffee = next(r for r in results if r["ingredient_id"] == "coffee_beans")
    # Weighted avg: (44 + 54) / (2000 + 3000) = 98 / 5000 = 0.0196
    assert coffee["weighted_avg_cost"] == pytest.approx(0.0196, abs=0.0001)
    assert coffee["total_spend_eur"] == pytest.approx(98.0)
    assert coffee["total_base_units"] == pytest.approx(5000.0)
    assert coffee["num_line_items"] == 2


def test_ingredient_costs_single_purchase(db_with_data):
    results = calculate_ingredient_costs(db_with_data)

    milk = next(r for r in results if r["ingredient_id"] == "whole_milk")
    assert milk["weighted_avg_cost"] == pytest.approx(0.0014, abs=0.0001)
    assert milk["num_receipts"] == 1


def test_menu_item_costs_margins(db_with_data):
    with open("menu.json") as f:
        menu_data = json.load(f)

    # First need ingredient costs
    calculate_ingredient_costs(db_with_data)
    results = calculate_menu_item_costs(db_with_data, menu_data)

    # Espresso: 18g coffee + 1 cup_8oz + 1 lid = 18 * 0.0196 + cup + lid
    espresso = next(r for r in results if r["menu_item_id"] == "espresso")
    assert espresso["sell_price"] == 2.50
    assert espresso["total_cogs"] > 0
    assert espresso["gross_margin_pct"] > 0
    # Margin should be positive (sell > cost for coffee alone)


def test_menu_item_combo_resolution(db_with_data):
    with open("menu.json") as f:
        menu_data = json.load(f)

    calculate_ingredient_costs(db_with_data)
    results = calculate_menu_item_costs(db_with_data, menu_data)

    morning = next(r for r in results if r["menu_item_id"] == "morning_deal")
    cappuccino = next(r for r in results if r["menu_item_id"] == "cappuccino")
    croissant = next(r for r in results if r["menu_item_id"] == "butter_croissant")

    # Combo COGS = sum of components
    expected_cogs = cappuccino["total_cogs"] + croissant["total_cogs"]
    assert morning["total_cogs"] == pytest.approx(expected_cogs, abs=0.01)
    assert morning["sell_price"] == 5.50


def test_expense_summary(db_with_data):
    results = calculate_expense_summary(db_with_data)

    categories = {r["category"] for r in results}
    assert "menu_ingredient" in categories
    assert "operational_food" in categories

    menu_ing = next(r for r in results if r["category"] == "menu_ingredient")
    assert menu_ing["total_spend_eur"] > 0

    op_food = next(r for r in results if r["category"] == "operational_food")
    assert op_food["total_spend_eur"] == pytest.approx(7.50)


def test_margin_formula(db_with_data):
    """Verify margin formula: (sell - cogs) / sell * 100."""
    with open("menu.json") as f:
        menu_data = json.load(f)

    calculate_ingredient_costs(db_with_data)
    results = calculate_menu_item_costs(db_with_data, menu_data)

    for item in results:
        if item["total_cogs"] > 0:
            expected_margin = (item["sell_price"] - item["total_cogs"]) / item["sell_price"] * 100
            assert item["gross_margin_pct"] == pytest.approx(expected_margin, abs=0.1)
