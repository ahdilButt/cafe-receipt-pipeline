"""
Pass 1: Vision API — Supplier Identification (Reconnaissance).

Sends the receipt image to Claude Vision with a list of known suppliers.
Returns: supplier match, date, currency, format, quality, observations.
"""

import anthropic
from pathlib import Path
from src.models import Pass1Result
from src.utils import parse_llm_response

LLM_MODEL = "claude-sonnet-4-20250514"
PASS1_MAX_TOKENS = 1024

PROMPT_PATH = Path(__file__).parent / "prompts" / "pass1.txt"


def build_pass1_prompt(supplier_list: list[dict]) -> str:
    """Build the Pass 1 prompt text from the known suppliers list."""
    template = PROMPT_PATH.read_text(encoding="utf-8")

    # Format supplier list for the prompt
    lines = []
    for s in supplier_list:
        name = s["name"]
        variations = s.get("name_variations", "[]")
        currency = s.get("default_currency", "EUR")
        lines.append(f"  - {name} (variations: {variations}, currency: {currency})")

    supplier_text = "\n".join(lines)
    return template.replace("{supplier_list}", supplier_text)


def run_pass1(client: anthropic.Anthropic, image_b64: str,
              supplier_list: list[dict]) -> Pass1Result:
    """Execute Pass 1 Vision API call for one receipt image."""
    prompt = build_pass1_prompt(supplier_list)

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=PASS1_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "data": image_b64, "media_type": "image/jpeg"}
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    response_text = response.content[0].text
    return parse_llm_response(response_text, Pass1Result)
