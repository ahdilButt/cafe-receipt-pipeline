"""
Seed data for the receipt processing pipeline.

Populates: suppliers (6), canonical_ingredients (21),
unit_conversions (12+), currency_rates (2).
"""

SUPPLIERS = [
    {
        "supplier_id": 1,
        "name": "Brennan & Sons Coffee Roasters",
        "name_variations": '["BRENNAN & SONS COFFEE ROASTERS", "Brennan & Sons Coffee Roasters", "Brennan & Sons"]',
        "format_variants": '["formal_invoice", "thermal_receipt"]',
        "languages": '["English"]',
        "default_currency": "EUR",
        "typical_items": '["coffee_beans", "coffee_filter_papers"]',
        "quirks": '["Formal invoices include VAT line (0%), payment terms (Net 30), IBAN", "Invoice numbers: INV-YYYY-NNNN on invoices, RNNN on thermal"]',
        "known_aliases": '{"Arabica Blend Coffee Beans 1kg": "coffee_beans", "Arabica Blend 1kg": "coffee_beans", "House Blend 1kg": "coffee_beans", "Decaf Blend 500g": "coffee_beans", "Coffee Filter Papers x200": "operational_supply"}',
    },
    {
        "supplier_id": 2,
        "name": "Mercato Fresco",
        "name_variations": '["\\u2605 MERCATO FRESCO \\u2605", "MERCATO FRESCO", "Mercato Fresco"]',
        "format_variants": '["thermal_receipt", "thermal_receipt_corrected"]',
        "languages": '["Italian", "English"]',
        "default_currency": "EUR",
        "typical_items": '["lemon", "fresh_mint", "avocado", "mixed_berries", "oranges", "tomatoes"]',
        "quirks": '["Uses Italian item names interchangeably with English", "Mazzo = bunch", "Handwritten corrections in red ink observed", "Grazie! sometimes at footer"]',
        "known_aliases": '{"Limoni": "lemon", "Lemons": "lemon", "Menta (mazzo)": "fresh_mint", "Fresh Mint (bunch)": "fresh_mint", "Avocado": "avocado", "Oranges": "operational_food", "Tomatoes": "operational_food", "Pomodori": "operational_food", "Fiori (mazzo)": "non_operational"}',
    },
    {
        "supplier_id": 3,
        "name": "Boulangerie Petit Pierre",
        "name_variations": '["Boulangerie Petit Pierre"]',
        "format_variants": '["handwritten"]',
        "languages": '["English"]',
        "default_currency": "EUR",
        "typical_items": '["croissant", "muffin", "scones", "chocolate_chip_cookies"]',
        "quirks": '["Handwritten receipts on paper", "No formal receipt ID \\u2014 use filename", "Date format: DD Mon YYYY", "Uses @ symbol for unit price"]',
        "known_aliases": '{"Croissants": "croissant", "Blueberry Muffins": "muffin", "Scones": "operational_food", "Chocolate Chip Cookies": "operational_food"}',
    },
    {
        "supplier_id": 4,
        "name": "De Melkboer Dairy",
        "name_variations": '["De Melkboer Dairy"]',
        "format_variants": '["thermal_receipt"]',
        "languages": '["English"]',
        "default_currency": "EUR",
        "typical_items": '["whole_milk", "oat_milk", "butter", "cream", "almond_milk"]',
        "quirks": '["Thermal receipts with ==== separator lines", "Can suffer from fading and physical damage", "Price variation observed across dates"]',
        "known_aliases": '{"Whole Milk 2L": "whole_milk", "Oat Milk 1L": "oat_milk", "Butter 250g": "operational_food", "Cream 500ml": "operational_food", "Almond Milk 1L": "operational_food"}',
    },
    {
        "supplier_id": 5,
        "name": "PackRight Supplies",
        "name_variations": '["PACKRIGHT SUPPLIES", "PackRight Supplies"]',
        "format_variants": '["thermal_receipt"]',
        "languages": '["English"]',
        "default_currency": "EUR",
        "typical_items": '["napkin", "paper_bag", "cup_8oz", "cup_12oz", "cup_16oz", "lid", "straw", "wooden_stirrers"]',
        "quirks": '["All items are consumables/packaging", "Pack sizes embedded in description", "Qty column = number of packs, NOT individual items", "Uses Order: instead of Receipt: for ID label"]',
        "known_aliases": '{"Napkins (pack of 1000)": "napkin", "Paper Bags (pack of 200)": "paper_bag", "Wooden Stirrers (500)": "operational_supply"}',
    },
    {
        "supplier_id": 6,
        "name": "London Coffee Traders Ltd",
        "name_variations": '["LONDON COFFEE TRADERS LTD", "London Coffee Traders Ltd"]',
        "format_variants": '["formal_invoice"]',
        "languages": '["English"]',
        "default_currency": "GBP",
        "typical_items": '["coffee_beans", "equipment_services"]',
        "quirks": '["Bills in GBP not EUR", "Uses imperial weight (lbs)", "May include service items", "Invoice numbers: LCT-YYYY-NNNN", "Date format: DD Month YYYY"]',
        "known_aliases": '{"Premium Arabica 2lb": "coffee_beans", "Coffee Grinder Repair": "equipment_service"}',
    },
]

CANONICAL_INGREDIENTS = [
    # Menu Ingredients (food/drink components)
    {"ingredient_id": "coffee_beans",   "display_name": "Coffee Beans",      "category": "coffee",    "base_unit": "g"},
    {"ingredient_id": "whole_milk",     "display_name": "Whole Milk",        "category": "dairy",     "base_unit": "ml"},
    {"ingredient_id": "oat_milk",       "display_name": "Oat Milk",          "category": "dairy",     "base_unit": "ml"},
    {"ingredient_id": "cocoa_powder",   "display_name": "Cocoa Powder",      "category": "sweetener", "base_unit": "g"},
    {"ingredient_id": "sugar",          "display_name": "Sugar",             "category": "sweetener", "base_unit": "g"},
    {"ingredient_id": "honey",          "display_name": "Honey",             "category": "sweetener", "base_unit": "g"},
    {"ingredient_id": "lemon",          "display_name": "Lemon",             "category": "produce",   "base_unit": "each"},
    {"ingredient_id": "fresh_mint",     "display_name": "Fresh Mint",        "category": "produce",   "base_unit": "leaves"},
    {"ingredient_id": "mixed_berries",  "display_name": "Mixed Berries",     "category": "produce",   "base_unit": "g"},
    {"ingredient_id": "avocado",        "display_name": "Avocado",           "category": "produce",   "base_unit": "each"},
    {"ingredient_id": "bread_loaf",     "display_name": "Bread Loaf",        "category": "bakery",    "base_unit": "slice"},
    {"ingredient_id": "salt",           "display_name": "Salt",              "category": "seasoning", "base_unit": "g"},
    {"ingredient_id": "croissant",      "display_name": "Croissant",         "category": "bakery",    "base_unit": "each"},
    {"ingredient_id": "muffin",         "display_name": "Blueberry Muffin",  "category": "bakery",    "base_unit": "each"},
    # Menu Consumables (packaging/serving items in recipes)
    {"ingredient_id": "cup_8oz",        "display_name": "Cup 8oz",           "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "cup_12oz",       "display_name": "Cup 12oz",          "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "cup_16oz",       "display_name": "Cup 16oz",          "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "lid",            "display_name": "Lid",               "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "straw",          "display_name": "Straw",             "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "paper_bag",      "display_name": "Paper Bag",         "category": "packaging", "base_unit": "each"},
    {"ingredient_id": "napkin",         "display_name": "Napkin",            "category": "packaging", "base_unit": "each"},
]

UNIT_CONVERSIONS = [
    # Generic metric conversions (ingredient_id = None)
    {"ingredient_id": None, "from_unit": "kg",  "to_unit": "g",  "factor": 1000.0,   "source": "standard"},
    {"ingredient_id": None, "from_unit": "lb",  "to_unit": "g",  "factor": 453.592,  "source": "standard"},
    {"ingredient_id": None, "from_unit": "L",   "to_unit": "ml", "factor": 1000.0,   "source": "standard"},
    # Ingredient-specific conversions
    {"ingredient_id": "coffee_beans", "from_unit": "1kg",   "to_unit": "g",     "factor": 1000.0,  "source": "standard",  "notes": "1kg bag -> g"},
    {"ingredient_id": "coffee_beans", "from_unit": "500g",  "to_unit": "g",     "factor": 500.0,   "source": "standard",  "notes": "500g bag -> g"},
    {"ingredient_id": "coffee_beans", "from_unit": "2lb",   "to_unit": "g",     "factor": 907.185, "source": "standard",  "notes": "2 x 453.592g"},
    {"ingredient_id": "whole_milk",   "from_unit": "2L",    "to_unit": "ml",    "factor": 2000.0,  "source": "standard",  "notes": "2L carton -> ml"},
    {"ingredient_id": "oat_milk",     "from_unit": "1L",    "to_unit": "ml",    "factor": 1000.0,  "source": "standard",  "notes": "1L carton -> ml"},
    {"ingredient_id": "fresh_mint",   "from_unit": "bunch", "to_unit": "leaves","factor": 20.0,    "source": "estimate",  "notes": "Estimated 20 leaves per bunch -- flagged"},
    {"ingredient_id": "bread_loaf",   "from_unit": "loaf",  "to_unit": "slice", "factor": 20.0,    "source": "estimate",  "notes": "Estimated 20 slices per loaf -- flagged"},
    {"ingredient_id": "napkin",       "from_unit": "pack_1000", "to_unit": "each", "factor": 1000.0, "source": "supplier_confirmed", "notes": "PackRight R025"},
    {"ingredient_id": "paper_bag",    "from_unit": "pack_200",  "to_unit": "each", "factor": 200.0,  "source": "supplier_confirmed", "notes": "PackRight R025"},
]

CURRENCY_RATES = [
    {"currency_code": "EUR", "to_eur_rate": 1.0,  "rate_date": "2024-10-01", "source": "base_currency",  "notes": "No conversion needed"},
    {"currency_code": "GBP", "to_eur_rate": 1.17, "rate_date": "2024-10-01", "source": "fixed_estimate", "notes": "Fixed estimate for Q4 2024. London Coffee Traders invoices."},
]
