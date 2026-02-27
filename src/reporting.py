"""
Report generation: cost_report.md and cost_report_prompt.txt.
"""

import json
import sqlite3
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_cost_report(conn: sqlite3.Connection, menu_data: dict) -> str:
    """Generate the full cost_report.md content as a markdown string."""
    lines = []

    # --- Executive Summary ---
    receipt_stats = conn.execute("""
        SELECT status, COUNT(*) FROM receipts GROUP BY status
    """).fetchall()
    status_map = dict(receipt_stats)
    total_receipts = sum(status_map.values())

    total_spend = conn.execute("""
        SELECT ROUND(SUM(line_total_eur), 2) FROM line_items WHERE line_total_eur IS NOT NULL
    """).fetchone()[0] or 0

    date_range = conn.execute("""
        SELECT MIN(date), MAX(date) FROM receipts WHERE date IS NOT NULL
    """).fetchone()
    earliest = date_range[0] or "unknown"
    latest = date_range[1] or "unknown"

    supplier_count = conn.execute("""
        SELECT COUNT(DISTINCT supplier_id) FROM receipts WHERE supplier_id IS NOT NULL
    """).fetchone()[0]

    lines.append(f"# Cafe Cost & Expense Report")
    lines.append(f"## Period: {earliest} to {latest}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(f"- Total receipts processed: {total_receipts} "
                 f"({status_map.get('complete', 0)} complete, "
                 f"{status_map.get('partial', 0)} partial, "
                 f"{status_map.get('failed', 0)} failed)")
    lines.append(f"- Total spending: EUR {total_spend:,.2f} across {supplier_count} suppliers")
    lines.append(f"- Menu COGS calculated for {len(menu_data.get('menu_items', []))} menu items")

    op_spend = conn.execute("""
        SELECT ROUND(SUM(line_total_eur), 2) FROM line_items
        WHERE expense_category NOT IN ('menu_ingredient', 'menu_consumable')
        AND line_total_eur IS NOT NULL
    """).fetchone()[0] or 0
    lines.append(f"- Operational + other costs: EUR {op_spend:,.2f}")
    lines.append("")

    # --- Section 1: Menu Item Cost & Margins ---
    lines.append("## 1. Menu Item Cost & Margins")
    lines.append("")
    lines.append("| Item | Category | Sell Price | COGS | Gross Margin % | Missing |")
    lines.append("|------|----------|-----------|------|----------------|---------|")

    menu_costs = conn.execute("""
        SELECT menu_item_name, category, sell_price, total_cogs,
               gross_margin_pct, missing_ingredients, notes
        FROM menu_item_costs ORDER BY category, menu_item_name
    """).fetchall()

    for row in menu_costs:
        name, cat, sell, cogs, margin, missing_json, notes = row
        missing = json.loads(missing_json) if missing_json else []
        missing_str = ", ".join(missing) if missing else "--"
        flag = " (!)" if margin < 50 else ""
        lines.append(f"| {name} | {cat} | EUR {sell:.2f} | EUR {cogs:.2f} | "
                     f"{margin:.1f}%{flag} | {missing_str} |")

    lines.append("")

    # Ingredient detail per menu item
    lines.append("### Ingredient Cost Detail per Menu Item")
    lines.append("")

    for row in menu_costs:
        name, cat, sell, cogs, margin, missing_json, notes = row
        lines.append(f"**{name}** (sell: EUR {sell:.2f}, COGS: EUR {cogs:.2f}, margin: {margin:.1f}%)")

        breakdown_row = conn.execute("""
            SELECT ingredient_breakdown FROM menu_item_costs WHERE menu_item_name = ?
        """, (name,)).fetchone()

        if breakdown_row and breakdown_row[0]:
            breakdown = json.loads(breakdown_row[0])
            for ing in breakdown:
                if "component" in ing:
                    lines.append(f"  - Component: {ing['component']} = EUR {ing.get('cogs', 0):.4f}")
                else:
                    cost_str = f"EUR {ing['total_cost']:.4f}" if ing.get('total_cost') is not None else "N/A"
                    lines.append(f"  - {ing['ingredient_id']}: {ing['quantity']} {ing['unit']} x "
                                 f"{ing.get('unit_cost', 'N/A')} = {cost_str}")

        if notes:
            lines.append(f"  Note: {notes}")
        lines.append("")

    # --- Section 2: Ingredient Cost Summary ---
    lines.append("## 2. Ingredient Cost Summary")
    lines.append("")
    lines.append("| Ingredient | Weighted Avg (EUR/unit) | Total Spend | Receipts | Price Range | Variance |")
    lines.append("|-----------|----------------------|-------------|----------|-------------|----------|")

    ing_costs = conn.execute("""
        SELECT i.display_name, ic.weighted_avg_cost, ic.total_spend_eur,
               ic.num_receipts, ic.min_cost, ic.max_cost, ic.price_variance_pct,
               i.base_unit
        FROM ingredient_costs ic
        JOIN canonical_ingredients i ON ic.ingredient_id = i.ingredient_id
        ORDER BY ic.total_spend_eur DESC
    """).fetchall()

    for row in ing_costs:
        name, avg, spend, receipts, min_c, max_c, var, unit = row
        range_str = f"{min_c:.4f}-{max_c:.4f}" if min_c and max_c else "--"
        var_str = f"{var:.1f}%" if var else "--"
        flag = " (!)" if var and var > 10 else ""
        lines.append(f"| {name} | {avg:.6f}/{unit} | EUR {spend:.2f} | {receipts} | "
                     f"{range_str} | {var_str}{flag} |")

    lines.append("")

    # --- Section 3: All Expenses by Category ---
    lines.append("## 3. All Expenses by Category")
    lines.append("")

    categories = conn.execute("""
        SELECT category, total_spend_eur, item_count, receipt_count, top_items
        FROM expense_summary ORDER BY total_spend_eur DESC
    """).fetchall()

    cat_labels = {
        "menu_ingredient": "3a. Menu Ingredients",
        "menu_consumable": "3b. Menu Consumables",
        "operational_food": "3c. Operational Food",
        "operational_supply": "3d. Operational Supplies",
        "equipment_service": "3e. Equipment & Services",
        "non_operational": "3f. Non-Operational",
        "unknown": "3g. Uncategorised",
    }

    for row in categories:
        cat, spend, items, receipts, top_json = row
        label = cat_labels.get(cat, cat)
        lines.append(f"### {label} -- EUR {spend:.2f}")
        lines.append(f"- {items} line items across {receipts} receipts")

        if top_json:
            top = json.loads(top_json)
            for t in top:
                lines.append(f"  - {t['item']}: EUR {t['spend']:.2f}")

        lines.append("")

    # --- Section 4: Supplier Summary ---
    lines.append("## 4. Supplier Summary")
    lines.append("")
    lines.append("| Supplier | Total Spend (EUR) | Receipts | Currency |")
    lines.append("|----------|------------------|----------|----------|")

    supplier_stats = conn.execute("""
        SELECT s.name, ROUND(SUM(li.line_total_eur), 2), COUNT(DISTINCT r.receipt_id),
               s.default_currency
        FROM receipts r
        JOIN suppliers s ON r.supplier_id = s.supplier_id
        JOIN line_items li ON r.receipt_id = li.receipt_id
        WHERE li.line_total_eur IS NOT NULL
        GROUP BY s.name
        ORDER BY SUM(li.line_total_eur) DESC
    """).fetchall()

    for row in supplier_stats:
        name, spend, receipts, currency = row
        lines.append(f"| {name} | EUR {spend:.2f} | {receipts} | {currency} |")

    lines.append("")

    # --- Section 5: Data Quality & Notes ---
    lines.append("## 5. Data Quality & Notes")
    lines.append("")

    # Partial/failed receipts
    problem_receipts = conn.execute("""
        SELECT receipt_id, status, notes FROM receipts WHERE status != 'complete'
    """).fetchall()

    if problem_receipts:
        lines.append("### Receipts with Issues")
        for r in problem_receipts:
            rid, status, notes = r
            lines.append(f"- **{rid}** ({status}): {notes or 'No notes'}")
        lines.append("")

    # Flagged items
    flagged = conn.execute("""
        SELECT receipt_id, raw_description, flag_reason
        FROM line_items WHERE is_flagged = 1
    """).fetchall()

    if flagged:
        lines.append("### Flagged Items")
        for f in flagged:
            rid, desc, reason = f
            lines.append(f"- {rid}: \"{desc}\" -- {reason}")
        lines.append("")

    # Assumptions
    lines.append("### Assumptions")
    lines.append("- GBP to EUR conversion: fixed rate 1.17 (Q4 2024 estimate)")
    lines.append("- Bread loaf: estimated 20 slices per loaf")
    lines.append("- Fresh mint bunch: estimated 20 leaves per bunch")
    lines.append("")

    # --- Section 6: Processing Audit ---
    lines.append("## 6. Processing Audit")

    api_calls = total_receipts * 3
    lines.append(f"- Receipts processed: {total_receipts}")
    lines.append(f"- API calls (estimated): {api_calls} (2 vision + 1 text per receipt)")

    error_count = conn.execute("""
        SELECT COUNT(*) FROM processing_log WHERE event_type = 'error'
    """).fetchone()[0]
    warning_count = conn.execute("""
        SELECT COUNT(*) FROM processing_log WHERE event_type = 'warning'
    """).fetchone()[0]
    lines.append(f"- Processing errors: {error_count}")
    lines.append(f"- Processing warnings: {warning_count}")
    lines.append("")

    return "\n".join(lines)


def generate_cost_report_prompt(conn: sqlite3.Connection) -> str:
    """Generate cost_report_prompt.txt — an LLM prompt for owner summary."""
    # Gather key numbers
    total_spend = conn.execute("""
        SELECT ROUND(SUM(line_total_eur), 2) FROM line_items WHERE line_total_eur IS NOT NULL
    """).fetchone()[0] or 0

    menu_costs = conn.execute("""
        SELECT menu_item_name, sell_price, total_cogs, gross_margin_pct
        FROM menu_item_costs ORDER BY gross_margin_pct
    """).fetchall()

    lowest_margin = menu_costs[0] if menu_costs else None
    highest_margin = menu_costs[-1] if menu_costs else None

    top_spend = conn.execute("""
        SELECT category, total_spend_eur FROM expense_summary ORDER BY total_spend_eur DESC LIMIT 3
    """).fetchall()

    prompt = f"""You are writing a brief, friendly summary for the cafe owner.
Based on the cost analysis below, write a 2-3 paragraph plain-language summary
covering: overall spending, which menu items have the best and worst margins,
and any concerns or recommendations.

KEY NUMBERS:
- Total spending across all receipts: EUR {total_spend:.2f}
- Top expense categories: {', '.join(f'{r[0]} (EUR {r[1]:.2f})' for r in top_spend)}
"""

    if lowest_margin:
        prompt += f"- Lowest margin item: {lowest_margin[0]} at {lowest_margin[3]:.1f}% margin (sell EUR {lowest_margin[1]:.2f}, cost EUR {lowest_margin[2]:.2f})\n"
    if highest_margin:
        prompt += f"- Highest margin item: {highest_margin[0]} at {highest_margin[3]:.1f}% margin (sell EUR {highest_margin[1]:.2f}, cost EUR {highest_margin[2]:.2f})\n"

    prompt += """
MENU ITEM MARGINS:
"""
    for row in menu_costs:
        name, sell, cogs, margin = row
        prompt += f"  {name}: sell EUR {sell:.2f}, cost EUR {cogs:.2f}, margin {margin:.1f}%\n"

    prompt += """
Write in a warm, professional tone. Mention specific numbers.
Flag any items with margin below 50% as needing attention.
Suggest checking if any operational food items should be added to the menu.
"""

    return prompt


def write_reports(conn: sqlite3.Connection, menu_data: dict) -> None:
    """Generate and write both report files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report = generate_cost_report(conn, menu_data)
    (OUTPUT_DIR / "cost_report.md").write_text(report, encoding="utf-8")

    prompt = generate_cost_report_prompt(conn)
    (OUTPUT_DIR / "cost_report_prompt.txt").write_text(prompt, encoding="utf-8")
