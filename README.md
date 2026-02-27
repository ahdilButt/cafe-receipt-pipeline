# Cafe Receipt COGS Pipeline

A data pipeline that processes 40 real cafe receipt images from 6 different suppliers, extracts line items using vision AI, maps ingredients to menu recipes, and calculates the true cost of goods sold (COGS) per menu item.

## The Problem

A cafe buys ingredients and supplies from multiple suppliers. The receipts come in different formats — formal invoices, thermal receipts, handwritten notes — some in Italian, some faded or damaged. The owner needs to know: **"What does each item on my menu actually cost to produce?"**

This pipeline answers that question end to end.

## How It Works

The pipeline uses a **3-pass architecture** per receipt:

1. **Pass 1 — Reconnaissance** (Vision API): Identifies the supplier, currency, date, and image quality
2. **Pass 2 — Extraction** (Vision API): Reads every line item with quantities, prices, and pack sizes
3. **Pass 3 — Categorisation** (Text API): Maps each item to a canonical ingredient and expense category

Each pass returns structured JSON validated by Pydantic models. Between passes, code-based validation checks line math, receipt totals, and category consistency.

After all receipts are processed, the pipeline:
- Converts all prices to EUR with unit normalisation (kg→g, L→ml, packs→individual units)
- Calculates weighted average costs per ingredient across all receipts
- Multiplies recipe quantities by ingredient costs to get per-menu-item COGS
- Generates a margin analysis and cost report

## Results

| Item | Sell Price | COGS | Margin |
|------|-----------|------|--------|
| Espresso | EUR 2.50 | EUR 0.62 | 75.1% |
| Cappuccino | EUR 3.80 | EUR 0.88 | 76.7% |
| Blueberry Muffin | EUR 3.20 | EUR 1.92 | 40.0% |
| Avocado Toast | EUR 6.50 | EUR 1.01 | 84.4% |

Full results for all 12 menu items in `output/cost_report.md`.

**Processing stats**: 38 complete, 1 partial, 1 failed out of 40 receipts.

## Architecture

```
main.py                       Entry point — setup, process, aggregate, report

src/
  models.py                   Pydantic models for all pipeline stages
  database.py                 SQLite schema (11 tables) and CRUD
  seed_data.py                Reference data: suppliers, ingredients, conversions
  pass1_recon.py              Vision API — supplier identification
  pass2_extract.py            Vision API — line item extraction
  pass3_categorise.py         Text API — ingredient matching & categorisation
  pipeline.py                 Orchestrator — runs all passes per receipt
  validation.py               Code-based math and consistency checks
  conversion.py               Unit conversion (weight/volume + discrete count)
  aggregation.py              Weighted averages, COGS, margins
  reporting.py                Generates cost report and summary prompt
  prompts/                    LLM prompt templates for each pass

tests/
  test_validation.py          18 tests — math checks, total matching, status
  test_conversion.py          29 tests — unit parsing, Track A/B, currency
  test_aggregation.py         6 tests — weighted averages, COGS, combos
```

## Key Design Decisions

- **Multi-pass over single-pass**: A single "read and categorise everything" prompt produces worse results. Splitting into focused passes improves accuracy.
- **Two conversion tracks**: Weight/volume items (coffee, milk) go through unit conversion. Discrete items (cups, lids) use pack arithmetic. Pass 3 decides which track.
- **Graceful degradation**: If Pass 1 fails, the receipt is marked `failed`. If Pass 3 fails, raw data from Passes 1+2 is still preserved with status `partial`.
- **Code validates LLM output**: Every LLM response is validated by Pydantic. Math checks run between passes. The LLM extracts; code verifies.

See [APPROACH.md](APPROACH.md) for a detailed technical walkthrough.

## Quick Start

```bash
pip install -r requirements.txt

# Set your Anthropic API key
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# Receipt images are included in data/receipts/
# Run the full pipeline
python main.py

# Run tests (no API key needed)
python -m pytest tests/ --ignore=tests/phase_tests -v
```

## Output

| File | Description |
|------|-------------|
| `output/cogs.db` | SQLite database with all 11 tables |
| `output/cost_report.md` | Full cost and margin report |
| `output/cost_report_prompt.txt` | LLM prompt for generating an owner-friendly summary |

## Tech Stack

- Python 3.11+
- Anthropic API (Claude Vision + Text)
- SQLite
- Pydantic for data validation
- pytest (53 tests)
