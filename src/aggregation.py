"""
Aggregation module: weighted averages, COGS, margins, expense summary.

Reads from line_items, calculates ingredient costs, menu item costs,
and writes results to ingredient_costs, menu_item_costs, expense_summary tables.
"""

import json
import sqlite3
from typing import Optional


def calculate_ingredient_costs(conn: sqlite3.Connection) -> list[dict]:
    """Calculate weighted average costs for each canonical ingredient."""
    rows = conn.execute("""
        SELECT canonical_ingredient_id,
               SUM(line_total_eur) as total_spend,
               SUM(base_unit_quantity) as total_units,
               COUNT(DISTINCT receipt_id) as num_receipts,
               COUNT(*) as num_items,
               MIN(cost_per_base_unit) as min_cost,
               MAX(cost_per_base_unit) as max_cost
        FROM line_items
        WHERE canonical_ingredient_id IS NOT NULL
          AND cost_per_base_unit IS NOT NULL
          AND line_total_eur IS NOT NULL
          AND base_unit_quantity IS NOT NULL
          AND base_unit_quantity > 0
        GROUP BY canonical_ingredient_id
    """).fetchall()

    results = []

    # Clear existing data
    conn.execute("DELETE FROM ingredient_costs")

    for row in rows:
        ing_id, total_spend, total_units, num_receipts, num_items, min_cost, max_cost = row

        if total_units and total_units > 0:
            weighted_avg = total_spend / total_units
        else:
            weighted_avg = 0

        variance_pct = None
        if weighted_avg and weighted_avg > 0 and min_cost is not None and max_cost is not None:
            variance_pct = round(((max_cost - min_cost) / weighted_avg) * 100, 2)

        result = {
            "ingredient_id": ing_id,
            "total_spend_eur": round(total_spend, 4),
            "total_base_units": round(total_units, 4),
            "weighted_avg_cost": round(weighted_avg, 6),
            "num_receipts": num_receipts,
            "num_line_items": num_items,
            "min_cost": round(min_cost, 6) if min_cost else None,
            "max_cost": round(max_cost, 6) if max_cost else None,
            "price_variance_pct": variance_pct,
        }
        results.append(result)

        notes = []
        if variance_pct and variance_pct > 10:
            notes.append(f"Price variance {variance_pct}% exceeds 10% threshold")

        conn.execute("""
            INSERT OR REPLACE INTO ingredient_costs
            (ingredient_id, total_spend_eur, total_base_units, weighted_avg_cost,
             num_receipts, num_line_items, min_cost, max_cost, price_variance_pct,
             calculation_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ing_id, result["total_spend_eur"], result["total_base_units"],
              result["weighted_avg_cost"], num_receipts, num_items,
              result["min_cost"], result["max_cost"], variance_pct,
              "; ".join(notes) if notes else None))

    conn.commit()
    return results


def calculate_menu_item_costs(conn: sqlite3.Connection,
                              menu_data: dict) -> list[dict]:
    """Calculate COGS and margins for each menu item."""
    # Load ingredient costs into a dict
    ingredient_costs = {}
    for row in conn.execute("SELECT ingredient_id, weighted_avg_cost FROM ingredient_costs").fetchall():
        ingredient_costs[row[0]] = row[1]

    results = []
    item_cogs = {}  # Store for combo resolution

    # Clear existing data
    conn.execute("DELETE FROM menu_item_costs")

    # First pass: calculate non-combo items
    for menu_item in menu_data.get("menu_items", []):
        recipe = menu_item.get("recipe", {})
        if "components" in recipe:
            continue  # Handle combos in second pass

        item_id = menu_item["id"]
        item_name = menu_item["name"]
        category = menu_item["category"]
        sell_price = menu_item["sell_price"]

        total_cogs = 0
        breakdown = []
        missing = []

        for ing in recipe.get("ingredients", []):
            ing_id = ing["item"]
            qty = ing["quantity"]
            unit = ing["unit"]

            avg_cost = ingredient_costs.get(ing_id)
            if avg_cost is not None:
                ing_cost = qty * avg_cost
                total_cogs += ing_cost
                breakdown.append({
                    "ingredient_id": ing_id,
                    "quantity": qty,
                    "unit": unit,
                    "unit_cost": round(avg_cost, 6),
                    "total_cost": round(ing_cost, 4),
                })
            else:
                missing.append(ing_id)
                breakdown.append({
                    "ingredient_id": ing_id,
                    "quantity": qty,
                    "unit": unit,
                    "unit_cost": None,
                    "total_cost": None,
                })

        total_cogs = round(total_cogs, 4)
        gross_profit = round(sell_price - total_cogs, 4)
        gross_margin_pct = round((gross_profit / sell_price) * 100, 2) if sell_price > 0 else 0
        markup_pct = round((gross_profit / total_cogs) * 100, 2) if total_cogs > 0 else 0

        result = {
            "menu_item_id": item_id,
            "menu_item_name": item_name,
            "category": category,
            "sell_price": sell_price,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "markup_pct": markup_pct,
            "ingredient_breakdown": breakdown,
            "missing_ingredients": missing,
        }
        results.append(result)
        item_cogs[item_id] = total_cogs

        notes = []
        if missing:
            notes.append(f"Missing cost data for: {', '.join(missing)}")
        if gross_margin_pct < 50:
            notes.append(f"Low margin warning: {gross_margin_pct}%")

        conn.execute("""
            INSERT OR REPLACE INTO menu_item_costs
            (menu_item_id, menu_item_name, category, sell_price, total_cogs,
             gross_profit, gross_margin_pct, markup_pct, ingredient_breakdown,
             missing_ingredients, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, item_name, category, sell_price, total_cogs,
              gross_profit, gross_margin_pct, markup_pct,
              json.dumps(breakdown), json.dumps(missing) if missing else None,
              "; ".join(notes) if notes else None))

    # Second pass: combo items
    for menu_item in menu_data.get("menu_items", []):
        recipe = menu_item.get("recipe", {})
        if "components" not in recipe:
            continue

        item_id = menu_item["id"]
        item_name = menu_item["name"]
        category = menu_item["category"]
        sell_price = menu_item["sell_price"]

        components = recipe["components"]
        total_cogs = sum(item_cogs.get(c, 0) for c in components)
        total_cogs = round(total_cogs, 4)

        gross_profit = round(sell_price - total_cogs, 4)
        gross_margin_pct = round((gross_profit / sell_price) * 100, 2) if sell_price > 0 else 0
        markup_pct = round((gross_profit / total_cogs) * 100, 2) if total_cogs > 0 else 0

        breakdown = [{"component": c, "cogs": round(item_cogs.get(c, 0), 4)} for c in components]
        missing = [c for c in components if c not in item_cogs]

        # Calculate individual total for comparison
        individual_total = sum(
            mi["sell_price"] for mi in menu_data["menu_items"]
            if mi["id"] in components
        )

        result = {
            "menu_item_id": item_id,
            "menu_item_name": item_name,
            "category": category,
            "sell_price": sell_price,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "markup_pct": markup_pct,
            "ingredient_breakdown": breakdown,
            "missing_ingredients": missing,
        }
        results.append(result)
        item_cogs[item_id] = total_cogs

        notes = [f"Combo: {' + '.join(components)}",
                 f"Individual total: EUR {individual_total:.2f}, combo saves EUR {individual_total - sell_price:.2f}"]

        conn.execute("""
            INSERT OR REPLACE INTO menu_item_costs
            (menu_item_id, menu_item_name, category, sell_price, total_cogs,
             gross_profit, gross_margin_pct, markup_pct, ingredient_breakdown,
             missing_ingredients, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, item_name, category, sell_price, total_cogs,
              gross_profit, gross_margin_pct, markup_pct,
              json.dumps(breakdown), json.dumps(missing) if missing else None,
              "; ".join(notes)))

    conn.commit()
    return results


def calculate_expense_summary(conn: sqlite3.Connection) -> list[dict]:
    """Summarize expenses by category."""
    rows = conn.execute("""
        SELECT expense_category,
               ROUND(SUM(line_total_eur), 2) as total_spend,
               COUNT(*) as item_count,
               COUNT(DISTINCT receipt_id) as receipt_count
        FROM line_items
        WHERE line_total_eur IS NOT NULL
        GROUP BY expense_category
        ORDER BY total_spend DESC
    """).fetchall()

    results = []

    # Clear existing data
    conn.execute("DELETE FROM expense_summary")

    for row in rows:
        category, total_spend, item_count, receipt_count = row

        # Get top items by spend
        top_items = conn.execute("""
            SELECT raw_description, ROUND(SUM(line_total_eur), 2) as spend
            FROM line_items
            WHERE expense_category = ? AND line_total_eur IS NOT NULL
            GROUP BY raw_description
            ORDER BY spend DESC
            LIMIT 5
        """, (category,)).fetchall()

        top_items_list = [{"item": r[0], "spend": r[1]} for r in top_items]

        result = {
            "category": category,
            "total_spend_eur": total_spend,
            "item_count": item_count,
            "receipt_count": receipt_count,
            "top_items": top_items_list,
        }
        results.append(result)

        conn.execute("""
            INSERT INTO expense_summary
            (category, total_spend_eur, item_count, receipt_count, top_items)
            VALUES (?, ?, ?, ?, ?)
        """, (category, total_spend, item_count, receipt_count,
              json.dumps(top_items_list)))

    conn.commit()
    return results
