"""
Pass 3: Text API — Categorisation & Ingredient Matching.

Text-only API call (no image). Receives extracted line items from Pass 2,
full ingredient list, menu data, and supplier context.
Returns: categorisation for each item with ingredient matching and reasoning.
"""

import json
import anthropic
from pathlib import Path
from src.models import Pass3Result
from src.utils import parse_llm_response

LLM_MODEL = "claude-sonnet-4-20250514"
PASS3_MAX_TOKENS = 4096

PROMPT_PATH = Path(__file__).parent / "prompts" / "pass3.txt"


def _build_ingredient_usage_map(menu_data: dict) -> dict[str, list[str]]:
    """Build a map of ingredient_id -> list of menu item names that use it."""
    usage = {}
    for item in menu_data.get("menu_items", []):
        recipe = item.get("recipe", {})
        if "ingredients" in recipe:
            for ing in recipe["ingredients"]:
                ing_id = ing["item"]
                if ing_id not in usage:
                    usage[ing_id] = []
                usage[ing_id].append(item["name"])
    return usage


def _build_ingredient_selection_list(canonical_ingredients: list[dict],
                                      menu_data: dict) -> str:
    """Build the formatted ingredient selection list for the prompt."""
    usage_map = _build_ingredient_usage_map(menu_data)

    menu_ingredients = []
    menu_consumables = []

    for ing in canonical_ingredients:
        ing_id = ing["ingredient_id"]
        display = ing["display_name"]
        base_unit = ing["base_unit"]
        category = ing["category"]
        used_in = ", ".join(usage_map.get(ing_id, ["(not in current recipes)"]))

        line = f"  ID: {ing_id:<16s} | Name: {display:<20s} | Base unit: {base_unit:<6s} | Used in: {used_in}"

        if category == "packaging":
            menu_consumables.append(line)
        else:
            menu_ingredients.append(line)

    sections = []
    sections.append("MENU INGREDIENTS (food/drink components):")
    sections.extend(menu_ingredients)
    sections.append("")
    sections.append("MENU CONSUMABLES (packaging/serving items in recipes):")
    sections.extend(menu_consumables)

    return "\n".join(sections)


def build_pass3_prompt(line_items: list[dict], supplier_profile: dict,
                       canonical_ingredients: list[dict],
                       menu_data: dict) -> str:
    """Build Pass 3 prompt with all context."""
    template = PROMPT_PATH.read_text(encoding="utf-8")

    supplier_name = supplier_profile.get("name", "Unknown")

    # Get languages
    languages = supplier_profile.get("languages", '["English"]')
    if isinstance(languages, str):
        try:
            parsed = json.loads(languages)
            languages = ", ".join(parsed) if isinstance(parsed, list) else languages
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(languages, list):
        languages = ", ".join(languages)

    # Get known aliases
    known_aliases = supplier_profile.get("known_aliases", "{}")
    if isinstance(known_aliases, dict):
        known_aliases = json.dumps(known_aliases, indent=2)
    elif isinstance(known_aliases, str):
        try:
            parsed = json.loads(known_aliases)
            known_aliases = json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass

    # Format extracted items
    item_lines = []
    for item in line_items:
        idx = item.get("item_index", 0)
        desc = item.get("raw_description", "")
        qty = item.get("quantity", "?")
        unit = item.get("raw_unit", "?")
        price = item.get("unit_price", "?")
        total = item.get("line_total", "?")
        pack = item.get("pack_size")
        pack_str = f", Pack size: {pack}" if pack else ""
        item_lines.append(
            f'  {idx}. "{desc}" — Qty: {qty}, Unit: {unit}, '
            f'Unit Price: {price}, Line Total: {total}{pack_str}'
        )
    extracted_items = "\n".join(item_lines)

    # Build ingredient selection list
    ingredient_list = _build_ingredient_selection_list(canonical_ingredients, menu_data)

    # Build the receipt_id from context (not always available, use placeholder)
    receipt_id = supplier_profile.get("_receipt_id", "unknown")

    # Substitute all variables
    prompt = template.replace("{supplier_name}", supplier_name)
    prompt = prompt.replace("{languages}", str(languages))
    prompt = prompt.replace("{known_aliases}", known_aliases)
    prompt = prompt.replace("{extracted_items}", extracted_items)
    prompt = prompt.replace("{ingredient_selection_list}", ingredient_list)
    prompt = prompt.replace("{receipt_id}", receipt_id)

    return prompt


def run_pass3(client: anthropic.Anthropic, line_items: list[dict],
              supplier_profile: dict, canonical_ingredients: list[dict],
              menu_data: dict) -> Pass3Result:
    """Execute Pass 3 Text API call for one receipt's extracted items."""
    prompt = build_pass3_prompt(line_items, supplier_profile,
                                canonical_ingredients, menu_data)

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=PASS3_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )

    response_text = response.content[0].text
    return parse_llm_response(response_text, Pass3Result)
