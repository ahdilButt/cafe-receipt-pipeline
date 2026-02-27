"""
Cafe Receipt COGS Pipeline

Entry point for the receipt processing pipeline.
Run with: python main.py
"""

import json
import sys
from pathlib import Path

import anthropic

from src.database import get_connection, init_db, seed_db
from src.pipeline import process_single_receipt


def load_env_file():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        import os
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)


def main():
    # Load .env file for API key
    load_env_file()

    # Phase 1: Setup
    conn = get_connection()
    init_db(conn)
    seed_db(conn)

    with open("menu.json") as f:
        menu_data = json.load(f)

    client = anthropic.Anthropic()

    # Load reference data
    cursor = conn.execute("SELECT * FROM suppliers")
    cols = [d[0] for d in cursor.description]
    suppliers = [dict(zip(cols, row)) for row in cursor.fetchall()]

    cursor = conn.execute("SELECT * FROM canonical_ingredients")
    cols2 = [d[0] for d in cursor.description]
    ingredients = [dict(zip(cols2, row)) for row in cursor.fetchall()]

    # Discover receipt images
    images = sorted(Path("data/receipts").glob("*.jpg"))
    print(f"Found {len(images)} receipt images to process\n")

    # Phase 2: Process all receipts
    status_counts = {"complete": 0, "partial": 0, "failed": 0}

    for i, image_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] Processing {image_path.name}...", end=" ", flush=True)
        try:
            result = process_single_receipt(
                client, conn, image_path, suppliers, ingredients, menu_data
            )
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
            print(f"{result.status}")
        except Exception as e:
            status_counts["failed"] += 1
            print(f"CRASHED: {e}")

    # Summary
    print(f"\nProcessing complete:")
    print(f"  Complete: {status_counts['complete']}")
    print(f"  Partial:  {status_counts['partial']}")
    print(f"  Failed:   {status_counts['failed']}")

    # Phase 3: Aggregate
    from src.aggregation import (
        calculate_ingredient_costs,
        calculate_menu_item_costs,
        calculate_expense_summary,
    )

    print("\nCalculating costs and margins...")
    calculate_ingredient_costs(conn)
    calculate_menu_item_costs(conn, menu_data)
    calculate_expense_summary(conn)

    # Phase 4: Report
    from src.reporting import write_reports

    print("Generating reports...")
    write_reports(conn, menu_data)

    print("\nDone! Output files:")
    print("  output/cogs.db")
    print("  output/cost_report.md")
    print("  output/cost_report_prompt.txt")

    conn.close()


if __name__ == "__main__":
    main()
