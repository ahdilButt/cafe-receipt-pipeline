# Approach

## What this is

A local cafe has 40 supplier receipt images. This pipeline reads every receipt, extracts the line items, figures out what each item is (coffee beans? cups? cleaning spray?), converts everything to a common unit, and calculates how much each menu item actually costs to make.

The end result: a database and report showing that an Espresso costs EUR 0.62 to make and sells for EUR 2.50 (75% margin), while a Blueberry Muffin costs EUR 1.92 and sells for EUR 3.20 (40% margin — that one needs attention).

---

## The core idea: 3 LLM passes per receipt

A single "read this receipt and do everything" prompt doesn't work well. The LLM gets confused trying to identify the supplier, read every line item, AND categorise them all at once. So we split it into 3 focused calls:

**Pass 1 — Reconnaissance (Vision API)**
Looks at the image and answers: who is this supplier? What currency? What date? Is the image damaged? This gives us context for the next pass — for example, if it's Mercato Fresco, the items will be in Italian.

Code: `src/pass1_recon.py` | Prompt: `src/prompts/pass1.txt`

**Pass 2 — Extraction (Vision API)**
Now that we know the supplier, we read every line item. Quantity, unit, price, total. If there are corrections or crossed-out values on the receipt, capture those too. If items come in packs ("pack of 200"), capture the pack size.

Code: `src/pass2_extract.py` | Prompt: `src/prompts/pass2.txt`

**Pass 3 — Categorisation (Text API, no image)**
Takes the extracted text from Pass 2 and matches each item to our ingredient list. "Arabica Blend 1kg" → `coffee_beans`. "Cup Lids (fits all)" → `lid`. Also decides the expense category — is this a menu ingredient, a consumable, operational, or something else entirely?

This pass also sets a critical flag: `is_discrete_consumable`. Cups and lids are discrete (you count them). Coffee beans are not (you weigh them). This determines how we calculate cost per unit later.

Code: `src/pass3_categorise.py` | Prompt: `src/prompts/pass3.txt`

Each pass returns structured JSON, validated by Pydantic models (`src/models.py`). If the JSON is malformed or missing required fields, we catch it immediately rather than letting bad data flow downstream.

---

## How an Espresso gets its cost

This is the best way to understand the whole system. Let's trace it end to end.

**1. Receipts come in**

Across 40 receipts, the pipeline finds 15 line items that are coffee. They have different names — "Arabica Blend 1kg", "House Blend 1kg", "Decaf 500g", "Premium Arabica 2lb" — but Pass 3 matches them all to `coffee_beans`.

**2. Convert to a common unit**

Each purchase is in different units. The conversion module (`src/conversion.py`) normalises everything to grams:
- "Arabica Blend 1kg" × 2 → 2000g, cost EUR 44.00
- "Decaf 500g" × 1 → 500g, cost EUR 14.00
- "Premium Arabica 2lb" × 1 → 907g, cost EUR 21.64 (converted from GBP at 1.17)

**3. Calculate weighted average**

The aggregation module (`src/aggregation.py`) sums it all up:
- Total spent on coffee: EUR 642.75
- Total grams purchased: 24,907g
- **Weighted average: EUR 642.75 / 24,907g = 0.025806 EUR/g**

This goes into the `ingredient_costs` table.

**4. Look up the recipe**

`menu.json` says an Espresso needs: 18g coffee beans + 1 cup (8oz) + 1 lid.

The aggregation module (`src/aggregation.py` → `calculate_menu_item_costs()`) multiplies each ingredient by its average cost:
- 18g coffee × 0.025806 EUR/g = EUR 0.4645
- 1 cup (8oz) × 0.1185 EUR/each = EUR 0.1185
- 1 lid × 0.04 EUR/each = EUR 0.04

**Total COGS: EUR 0.6230**

**5. Calculate margin**

Sell price (from menu.json): EUR 2.50
Margin: (2.50 - 0.623) / 2.50 = **75.1%**

This goes into the `menu_item_costs` table, and from there into the report.

---

## Two tracks: weight vs count

Not everything is measured the same way. Coffee beans are sold by weight. Cups are sold by count. The pipeline handles these differently.

**Track A — Weight/Volume items** (coffee, milk, sugar, etc.)

These go through unit conversion. "1kg" becomes 1000g. "2lb" becomes 907g. "2L" becomes 2000ml. The conversion factors live in the `unit_conversions` table, and the code is in `src/conversion.py`.

Some conversions are estimates: a bunch of fresh mint = 20 leaves, a loaf of bread = 20 slices. These are documented in the assumptions section below.

The receipt might say the unit is "each" but the description says "Arabica Blend 1kg" — the code catches this and extracts the weight from the description. It also handles Italian units: "mazzo" (bunch) is normalised to "bunch".

**Track B — Discrete items** (cups, lids, napkins, straws, paper bags)

These are just counted. Two scenarios:
- Receipt says "Napkins (pack of 1000)" → qty=1, pack_size=1000 → total units = 1 × 1000 = 1000
- Receipt says "Cup Lids: 200 x EUR 0.04" → qty=200, pack_size=None → total units = 200 (the quantity IS the count)

Pass 3 decides which track each item takes by setting `is_discrete_consumable = true/false`.

---

## Validation between passes

After Pass 2 extracts line items, code-based validation runs before we hand anything to Pass 3:

- **Line math**: does qty × unit_price = line_total? (tolerance: EUR 0.02 for rounding)
- **Receipt total**: does the sum of line totals match the receipt total?
- **Corrections**: if the receipt has crossed-out values, are both the original and corrected values captured?

After Pass 3 categorises items, another check:
- **Category consistency**: menu ingredients must have an ingredient ID, operational items must not

These checks determine the receipt's final status: `complete`, `partial`, or `failed`.

Code: `src/validation.py` (53 unit tests cover all of this)

---

## Error handling

Not every receipt processes perfectly. The pipeline is designed to degrade gracefully:

- **Pass 1 fails** (can't identify supplier) → status = `failed`, store the filename only
- **Pass 2 fails** (can't read line items) → status = `failed`, store supplier info from Pass 1
- **Pass 3 fails** (can't categorise) → status = `partial`, store the raw line items without categories
- **Conversion fails** for one item → flag that item, continue with the rest

The pipeline orchestrator (`src/pipeline.py`) wraps each pass in try/except and logs everything to the `processing_log` table.

Final results: 38 complete, 1 partial, 1 failed out of 40 receipts.

---

## The database: 11 tables

All data lives in `output/cogs.db` (SQLite). Here's what each table does and why it exists.

### Reference tables (seeded at startup, never modified by the pipeline)

**`suppliers`** (6 rows) — Known supplier profiles.
Each supplier has `name_variations` (JSON array of possible spellings), `languages`, `quirks`, and `known_aliases`. This context gets injected into the LLM prompts so Pass 1 can match "PACKRIGHT SUPPLIES" to supplier_id=5, and Pass 3 knows that Mercato Fresco's "Limoni" means lemons.
Defined in: `src/seed_data.py`

**`canonical_ingredients`** (21 rows) — The master ingredient list, derived from menu.json.
Every menu item recipe references these IDs. `coffee_beans`, `whole_milk`, `cup_8oz`, `lid`, `napkin`, etc. Each has a `base_unit` (g, ml, each, leaves, slice) that everything gets converted to.
Defined in: `src/seed_data.py`

**`unit_conversions`** (12 rows) — How to convert between units.
Generic conversions: kg→g (×1000), lb→g (×453.592), L→ml (×1000).
Ingredient-specific: fresh_mint bunch→20 leaves, bread_loaf loaf→20 slices.
Defined in: `src/seed_data.py`, used by: `src/conversion.py`

**`currency_rates`** (2 rows) — EUR=1.0, GBP=1.17.
Only one receipt (R040, London Coffee Traders) uses GBP. Fixed rate, noted as an assumption.

### Pipeline output tables (populated during receipt processing)

**`receipts`** (40 rows) — One row per receipt image.
Stores supplier ID, date, currency, totals, quality assessment, status, and the LLM's reasoning from each pass (for audit). The status field (`complete`/`partial`/`failed`) is set by the validation logic.
Written by: `src/pipeline.py`

**`line_items`** (~98 rows) — Every item from every receipt.
This is the core data table. Each row has:
- What Pass 2 extracted: `raw_description`, `quantity`, `raw_unit`, `unit_price`, `line_total`
- What Pass 3 decided: `canonical_ingredient_id`, `expense_category`, `is_discrete_consumable`
- What conversion calculated: `line_total_eur`, `base_unit_quantity`, `cost_per_base_unit`
- Quality flags: `is_flagged`, `flag_reason` (3 items flagged in the final run — all non-menu items)
Written by: `src/pipeline.py`

**`processing_log`** (~122 rows) — Audit trail.
Every pipeline step logs here: "Pass 1 identified supplier as Brennan & Sons", "Pass 2 extracted 3 line items", "Validation warning: total mismatch". If something goes wrong with a specific receipt, you can trace exactly what happened.
Written by: `src/pipeline.py`

### Aggregation tables (computed after all receipts are processed)

**`ingredient_costs`** (15 rows) — Average cost per ingredient.
For each canonical ingredient, stores: total spend, total base units, weighted average cost, number of receipts, and price variance. Coffee beans: 0.025806 EUR/g across 9 receipts. Lids: 0.04 EUR/each across 3 receipts.
Written by: `src/aggregation.py` → `calculate_ingredient_costs()`

**`menu_item_costs`** (12 rows) — COGS and margin per menu item.
For each item in menu.json, multiplies recipe quantities by ingredient averages from the table above. Stores sell price, total COGS, gross margin %, and a JSON breakdown of each ingredient's contribution. Combo items (Morning Deal, Power Lunch) sum their component COGS.
Written by: `src/aggregation.py` → `calculate_menu_item_costs()`

**`expense_summary`** (6 rows) — Spend grouped by category.
menu_ingredient: EUR 1,357.85 | menu_consumable: EUR 368.50 | operational_food: EUR 212.60 | equipment_service: EUR 52.65 | operational_supply: EUR 30.10 | non_operational: EUR 12.00
Written by: `src/aggregation.py` → `calculate_expense_summary()`

**`unmatched_items`** (0 rows) — Reserved for items that couldn't be matched.
Designed for future use. Currently Pass 3 always assigns a category, so nothing ends up here. If the pipeline were extended with stricter matching, unmatched items would go here for human review.

---

## The expense taxonomy

Every line item gets one of 6 categories. This is decided by Pass 3 (the LLM) based on guidelines in the prompt:

| Category | What it means | Examples |
|---|---|---|
| `menu_ingredient` | Goes into a menu item recipe | Coffee beans, milk, sugar, lemons, avocado |
| `menu_consumable` | Packaging used when serving a menu item | Cups, lids, napkins, paper bags, straws |
| `operational_food` | Food the cafe uses but isn't on the menu | Scones, cookies, almond milk, cream |
| `operational_supply` | Non-food supplies | Cleaning spray, bleach, stirrers, filter papers |
| `equipment_service` | Equipment or repairs | Coffee grinder repair |
| `non_operational` | Nothing to do with the cafe | Flowers |

Only `menu_ingredient` and `menu_consumable` items feed into the COGS calculations. The rest are tracked as operational costs in the report.

---

## Assumptions

| What | Value | Why |
|---|---|---|
| GBP → EUR rate | 1.17 | Fixed Q4 2024 estimate. Only 1 of 40 receipts uses GBP (R040). |
| Bread loaf → slices | 20 per loaf | Standard sliced bread. No bread receipts exist in the dataset, so this is unused but ready. |
| Mint bunch → leaves | 20 per bunch | Estimate. Mercato Fresco sells mint by the "mazzo" (Italian for bunch). |
| "mazzo" → "bunch" | Unit normalisation | Italian unit from Mercato Fresco receipts. |
| Math tolerance | EUR 0.02 | Receipts sometimes round line totals. This tolerance prevents false validation failures. |

---

## Known limitations

**Missing ingredients**: Two menu item ingredients have no receipt data at all:
- `mixed_berries` — no berry purchases in the 40 receipts
- `bread_loaf` — no bread purchases found

This means Berry Smoothie and Avocado Toast COGS are slightly understated. The report flags these in the "Missing" column.

**Coffee bean price variance**: All coffee blends (Arabica, House Blend, Decaf, Special Blend, Premium Arabica) map to one `coffee_beans` ingredient. This creates 337% price variance — which is expected, not a bug. A premium single-origin at 0.105 EUR/g and a house blend at 0.018 EUR/g are very different products averaged together.

**LLM variability**: Running the pipeline again may produce slightly different results. Different wording in descriptions, minor rounding differences. The Pydantic validation and math checks catch anything structurally wrong, but the exact text may vary.

**One failed receipt**: R038 consistently fails at Pass 2 — the image is likely too damaged or ambiguous for the LLM to extract line items.

---

## Output files

| File | What it's for |
|---|---|
| `output/cogs.db` | The full SQLite database. Everything is here — query it directly for any analysis. |
| `output/cost_report.md` | A markdown report with 6 sections: executive summary, menu margins, ingredient costs, expense breakdown, supplier summary, and data quality notes. Built by `src/reporting.py` from SQL queries against the database — no LLM involved. |
| `output/cost_report_prompt.txt` | A ready-made prompt you can paste into any LLM to get a plain-language summary for the cafe owner. Includes all the key numbers so the LLM can write something friendly and actionable. |

---

## How to run

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key (create a .env file in the project root)
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# Run the full pipeline
python main.py

# Run the tests (53 tests, no API key needed)
python -m pytest tests/ --ignore=tests/phase_tests -v
```

Takes about 5-8 minutes for all 40 receipts (3 API calls each = ~120 calls total).

---

## Project structure

Every file has one job:

```
main.py                       Entry point. Runs the full pipeline: setup → process 40 receipts → aggregate → report.

menu.json                     The cafe's menu: 12 items with recipes, ingredients, and sell prices.
                              This is the source of truth for what ingredients we need to cost.

src/
  models.py                   All Pydantic models. Pass1Result, Pass2Result, Pass3Result,
                              ProcessedLineItem, ProcessedReceipt. Defines the shape of data
                              at every stage.

  database.py                 SQLite schema (11 tables) and all CRUD functions.
                              init_db() creates tables, insert_receipt() stores results.

  seed_data.py                Reference data loaded at startup: 6 suppliers, 21 ingredients,
                              12 unit conversions, 2 currency rates.

  pass1_recon.py              Pass 1. Loads the prompt template, sends the receipt image to
                              Claude Vision API, parses the JSON response. Returns supplier,
                              currency, date, quality.

  pass2_extract.py            Pass 2. Same pattern — Vision API call with supplier context from
                              Pass 1. Returns line items with quantities, prices, pack sizes.

  pass3_categorise.py         Pass 3. Text-only API call (no image). Matches each extracted item
                              to a canonical ingredient and assigns an expense category.

  pipeline.py                 The orchestrator. process_single_receipt() runs all 3 passes,
                              validation, conversion, and DB storage for one receipt.
                              Handles errors at each stage gracefully.

  validation.py               Code-based checks between passes. Line math, total matching,
                              correction detection, category consistency. Determines receipt status.

  conversion.py               Track A (weight/volume) and Track B (discrete count) conversion.
                              Currency conversion. Unit parsing ("1kg" → 1000g, "mazzo" → bunch).

  aggregation.py              Calculates weighted averages per ingredient, COGS per menu item,
                              and expense totals per category. Writes to the 3 aggregation tables.

  reporting.py                Generates cost_report.md and cost_report_prompt.txt from SQL
                              queries against the database. Pure code, no LLM calls.

  utils.py                    parse_llm_response() — strips code fences from LLM output,
                              parses JSON, validates with Pydantic.

  prompts/
    pass1.txt                 Prompt template for supplier reconnaissance.
    pass2.txt                 Prompt template for line item extraction.
    pass3.txt                 Prompt template for categorisation and ingredient matching.

tests/
  test_validation.py          18 tests for math checks, total matching, status determination.
  test_conversion.py          29 tests for Track A/B, currency, unit parsing, edge cases.
  test_aggregation.py         6 tests for weighted averages, COGS, margin formula, combo items.

output/
  cogs.db                     Generated SQLite database with all 11 tables.
  cost_report.md              Generated markdown report.
  cost_report_prompt.txt      Generated LLM prompt for owner-friendly summary.
```
