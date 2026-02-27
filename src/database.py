"""
SQLite database: 11-table schema, CRUD functions, and seed orchestration.
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "output" / "cogs.db"


def get_connection() -> sqlite3.Connection:
    """Return connection to output/cogs.db. Creates parent dirs if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all 11 tables. Idempotent (IF NOT EXISTS)."""
    conn.executescript("""
        -- Table 1: suppliers
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id     INTEGER PRIMARY KEY,
            name            TEXT NOT NULL,
            name_variations TEXT NOT NULL,
            format_variants TEXT NOT NULL,
            languages       TEXT NOT NULL DEFAULT '["English"]',
            default_currency TEXT NOT NULL DEFAULT 'EUR',
            typical_items   TEXT,
            quirks          TEXT,
            known_aliases   TEXT,
            notes           TEXT
        );

        -- Table 2: canonical_ingredients
        CREATE TABLE IF NOT EXISTS canonical_ingredients (
            ingredient_id   TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            category        TEXT NOT NULL,
            base_unit       TEXT NOT NULL,
            notes           TEXT
        );

        -- Table 3: unit_conversions
        CREATE TABLE IF NOT EXISTS unit_conversions (
            conversion_id   INTEGER PRIMARY KEY,
            ingredient_id   TEXT,
            from_unit       TEXT NOT NULL,
            to_unit         TEXT NOT NULL,
            factor          REAL NOT NULL,
            source          TEXT NOT NULL,
            notes           TEXT,
            FOREIGN KEY (ingredient_id) REFERENCES canonical_ingredients(ingredient_id)
        );

        -- Table 4: currency_rates
        CREATE TABLE IF NOT EXISTS currency_rates (
            currency_code   TEXT PRIMARY KEY,
            to_eur_rate     REAL NOT NULL,
            rate_date       TEXT,
            source          TEXT NOT NULL,
            notes           TEXT
        );

        -- Table 5: receipts
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id          TEXT PRIMARY KEY,
            filename            TEXT NOT NULL UNIQUE,
            invoice_number      TEXT,
            supplier_id         INTEGER,
            date                TEXT,
            receipt_total       REAL,
            currency            TEXT DEFAULT 'EUR',
            receipt_total_eur   REAL,
            status              TEXT NOT NULL DEFAULT 'pending',
            damage_type         TEXT DEFAULT 'none',
            has_corrections     BOOLEAN DEFAULT FALSE,
            image_quality       TEXT,
            pass1_reasoning     TEXT,
            pass2_reasoning     TEXT,
            pass3_reasoning     TEXT,
            notes               TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        );

        -- Table 6: line_items
        CREATE TABLE IF NOT EXISTS line_items (
            line_item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id              TEXT NOT NULL,
            raw_description         TEXT NOT NULL,
            quantity                REAL,
            raw_unit                TEXT,
            unit_price              REAL,
            line_total              REAL,
            currency                TEXT DEFAULT 'EUR',
            original_unit_price     REAL,
            original_line_total     REAL,
            correction_note         TEXT,
            canonical_ingredient_id TEXT,
            expense_category        TEXT NOT NULL DEFAULT 'unknown',
            category_reasoning      TEXT,
            match_confidence        TEXT,
            match_reasoning         TEXT,
            line_total_eur          REAL,
            base_unit_quantity      REAL,
            cost_per_base_unit      REAL,
            conversion_note         TEXT,
            pack_size               INTEGER,
            is_discrete_consumable  BOOLEAN DEFAULT FALSE,
            total_individual_units  REAL,
            is_flagged              BOOLEAN DEFAULT FALSE,
            flag_reason             TEXT,
            FOREIGN KEY (receipt_id) REFERENCES receipts(receipt_id),
            FOREIGN KEY (canonical_ingredient_id) REFERENCES canonical_ingredients(ingredient_id)
        );

        -- Table 7: processing_log
        CREATE TABLE IF NOT EXISTS processing_log (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id  TEXT NOT NULL,
            stage       TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            message     TEXT NOT NULL,
            reasoning   TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (receipt_id) REFERENCES receipts(receipt_id)
        );

        -- Table 8: unmatched_items
        CREATE TABLE IF NOT EXISTS unmatched_items (
            unmatched_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id              TEXT NOT NULL,
            line_item_id            INTEGER NOT NULL,
            raw_description         TEXT NOT NULL,
            suggested_match         TEXT,
            similarity_score        REAL,
            reason_no_match         TEXT NOT NULL,
            assigned_category       TEXT,
            resolved                BOOLEAN DEFAULT FALSE,
            resolved_to_ingredient  TEXT,
            FOREIGN KEY (receipt_id) REFERENCES receipts(receipt_id),
            FOREIGN KEY (line_item_id) REFERENCES line_items(line_item_id)
        );

        -- Table 9: ingredient_costs
        CREATE TABLE IF NOT EXISTS ingredient_costs (
            ingredient_id       TEXT PRIMARY KEY,
            total_spend_eur     REAL NOT NULL,
            total_base_units    REAL NOT NULL,
            weighted_avg_cost   REAL NOT NULL,
            num_receipts        INTEGER NOT NULL,
            num_line_items      INTEGER NOT NULL,
            min_cost            REAL,
            max_cost            REAL,
            price_variance_pct  REAL,
            last_updated        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            calculation_notes   TEXT,
            FOREIGN KEY (ingredient_id) REFERENCES canonical_ingredients(ingredient_id)
        );

        -- Table 10: menu_item_costs
        CREATE TABLE IF NOT EXISTS menu_item_costs (
            menu_item_id            TEXT PRIMARY KEY,
            menu_item_name          TEXT NOT NULL,
            category                TEXT NOT NULL,
            sell_price              REAL NOT NULL,
            total_cogs              REAL NOT NULL,
            gross_profit            REAL NOT NULL,
            gross_margin_pct        REAL NOT NULL,
            markup_pct              REAL NOT NULL,
            ingredient_breakdown    TEXT NOT NULL,
            missing_ingredients     TEXT,
            notes                   TEXT
        );

        -- Table 11: expense_summary
        CREATE TABLE IF NOT EXISTS expense_summary (
            category            TEXT NOT NULL,
            total_spend_eur     REAL NOT NULL,
            item_count          INTEGER NOT NULL,
            receipt_count       INTEGER NOT NULL,
            top_items           TEXT,
            notes               TEXT
        );
    """)
    conn.commit()


def seed_db(conn: sqlite3.Connection) -> None:
    """Seed suppliers, canonical_ingredients, unit_conversions, currency_rates.
    Idempotent (INSERT OR IGNORE)."""
    from src.seed_data import SUPPLIERS, CANONICAL_INGREDIENTS, UNIT_CONVERSIONS, CURRENCY_RATES

    for s in SUPPLIERS:
        conn.execute(
            """INSERT OR IGNORE INTO suppliers
               (supplier_id, name, name_variations, format_variants, languages,
                default_currency, typical_items, quirks, known_aliases, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s["supplier_id"], s["name"], s["name_variations"], s["format_variants"],
             s["languages"], s["default_currency"], s.get("typical_items"),
             s.get("quirks"), s.get("known_aliases"), s.get("notes"))
        )

    for i in CANONICAL_INGREDIENTS:
        conn.execute(
            """INSERT OR IGNORE INTO canonical_ingredients
               (ingredient_id, display_name, category, base_unit, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (i["ingredient_id"], i["display_name"], i["category"],
             i["base_unit"], i.get("notes"))
        )

    for u in UNIT_CONVERSIONS:
        # Check if this exact conversion already exists
        existing = conn.execute(
            """SELECT 1 FROM unit_conversions
               WHERE ingredient_id IS ? AND from_unit = ? AND to_unit = ?""",
            (u.get("ingredient_id"), u["from_unit"], u["to_unit"])
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO unit_conversions
                   (ingredient_id, from_unit, to_unit, factor, source, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (u.get("ingredient_id"), u["from_unit"], u["to_unit"],
                 u["factor"], u["source"], u.get("notes"))
            )

    for c in CURRENCY_RATES:
        conn.execute(
            """INSERT OR IGNORE INTO currency_rates
               (currency_code, to_eur_rate, rate_date, source, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (c["currency_code"], c["to_eur_rate"], c.get("rate_date"),
             c["source"], c.get("notes"))
        )

    conn.commit()


def get_supplier_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    """Match supplier name against name_variations JSON arrays.
    Returns supplier row as dict or None."""
    if not name:
        return None
    name_lower = name.lower().strip()
    cursor = conn.execute("SELECT * FROM suppliers")
    cols = [d[0] for d in cursor.description]
    for row in cursor.fetchall():
        supplier = dict(zip(cols, row))
        variations = json.loads(supplier["name_variations"])
        for variation in variations:
            if variation.lower().strip() == name_lower:
                return supplier
            if variation.lower() in name_lower or name_lower in variation.lower():
                return supplier
    return None


def get_supplier_profile(conn: sqlite3.Connection, supplier_id: int) -> dict:
    """Full supplier profile with parsed JSON fields."""
    cursor = conn.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
    cols = [d[0] for d in cursor.description]
    row = cursor.fetchone()
    if not row:
        return {}
    profile = dict(zip(cols, row))
    # Parse JSON fields
    for field in ["name_variations", "format_variants", "languages", "typical_items", "quirks"]:
        if profile.get(field):
            try:
                profile[field] = json.loads(profile[field])
            except (json.JSONDecodeError, TypeError):
                pass
    if profile.get("known_aliases"):
        try:
            profile["known_aliases"] = json.loads(profile["known_aliases"])
        except (json.JSONDecodeError, TypeError):
            pass
    return profile


def insert_receipt(conn: sqlite3.Connection, receipt) -> None:
    """Insert receipt row + all line_items. Single transaction."""
    conn.execute(
        """INSERT OR REPLACE INTO receipts
           (receipt_id, filename, invoice_number, supplier_id, date,
            receipt_total, currency, receipt_total_eur, status,
            damage_type, has_corrections, image_quality,
            pass1_reasoning, pass2_reasoning, pass3_reasoning, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (receipt.receipt_id, receipt.filename, receipt.invoice_number,
         receipt.supplier_id, receipt.date, receipt.receipt_total,
         receipt.currency, receipt.receipt_total_eur, receipt.status,
         receipt.damage_type, receipt.has_corrections, receipt.image_quality,
         receipt.pass1_reasoning, receipt.pass2_reasoning,
         receipt.pass3_reasoning, receipt.notes)
    )

    for li in receipt.line_items:
        conn.execute(
            """INSERT INTO line_items
               (receipt_id, raw_description, quantity, raw_unit, unit_price,
                line_total, currency, original_unit_price, original_line_total,
                correction_note, canonical_ingredient_id, expense_category,
                category_reasoning, match_confidence, match_reasoning,
                line_total_eur, base_unit_quantity, cost_per_base_unit,
                conversion_note, pack_size, is_discrete_consumable,
                total_individual_units, is_flagged, flag_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (receipt.receipt_id, li.raw_description, li.quantity, li.raw_unit,
             li.unit_price, li.line_total, li.currency,
             li.original_unit_price, li.original_line_total,
             li.correction_note, li.canonical_ingredient_id,
             li.expense_category.value if hasattr(li.expense_category, 'value') else li.expense_category,
             li.category_reasoning, li.match_confidence, li.match_reasoning,
             li.line_total_eur, li.base_unit_quantity, li.cost_per_base_unit,
             li.conversion_note, li.pack_size, li.is_discrete_consumable,
             li.total_individual_units, li.is_flagged, li.flag_reason)
        )

    conn.commit()


def insert_processing_log(conn: sqlite3.Connection, receipt_id: str,
                          stage: str, event_type: str, message: str,
                          reasoning: Optional[str] = None) -> None:
    """Append to processing_log."""
    conn.execute(
        """INSERT INTO processing_log
           (receipt_id, stage, event_type, message, reasoning)
           VALUES (?, ?, ?, ?, ?)""",
        (receipt_id, stage, event_type, message, reasoning)
    )
    conn.commit()


def insert_unmatched_item(conn: sqlite3.Connection, receipt_id: str,
                          line_item_id: int, raw_description: str,
                          reason_no_match: str, suggested_match: Optional[str] = None,
                          assigned_category: Optional[str] = None) -> None:
    """Record an unmatched item for human review."""
    conn.execute(
        """INSERT INTO unmatched_items
           (receipt_id, line_item_id, raw_description, reason_no_match,
            suggested_match, assigned_category)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (receipt_id, line_item_id, raw_description, reason_no_match,
         suggested_match, assigned_category)
    )
    conn.commit()


def get_conversion_factor(conn: sqlite3.Connection, ingredient_id: Optional[str],
                          from_unit: str, to_unit: str) -> Optional[float]:
    """Look up conversion factor. Tries ingredient-specific first, then generic."""
    if ingredient_id:
        row = conn.execute(
            """SELECT factor FROM unit_conversions
               WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?""",
            (ingredient_id, from_unit, to_unit)
        ).fetchone()
        if row:
            return row[0]

    # Try generic (ingredient_id IS NULL)
    row = conn.execute(
        """SELECT factor FROM unit_conversions
           WHERE ingredient_id IS NULL AND from_unit = ? AND to_unit = ?""",
        (from_unit, to_unit)
    ).fetchone()
    return row[0] if row else None


def get_currency_rate(conn: sqlite3.Connection, currency_code: str) -> Optional[float]:
    """Return to_eur_rate for given currency code."""
    row = conn.execute(
        "SELECT to_eur_rate FROM currency_rates WHERE currency_code = ?",
        (currency_code,)
    ).fetchone()
    return row[0] if row else None
