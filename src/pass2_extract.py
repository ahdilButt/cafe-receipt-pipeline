"""
Pass 2: Vision API — Line Item Extraction.

Sends the receipt image with supplier context from Pass 1.
Returns: all line items with quantities, prices, pack sizes, corrections.
"""

import json
import anthropic
from pathlib import Path
from src.models import Pass2Result, Pass1Result
from src.utils import parse_llm_response

LLM_MODEL = "claude-sonnet-4-20250514"
PASS2_MAX_TOKENS = 2048

PROMPT_PATH = Path(__file__).parent / "prompts" / "pass2.txt"


def build_pass2_prompt(supplier_profile: dict, pass1_result: Pass1Result) -> str:
    """Build Pass 2 prompt with supplier context injected."""
    template = PROMPT_PATH.read_text(encoding="utf-8")

    supplier_name = pass1_result.supplier_name or "Unknown"
    format_type = pass1_result.format_type.value if hasattr(pass1_result.format_type, 'value') else str(pass1_result.format_type)

    # Extract languages and quirks from supplier profile
    languages = supplier_profile.get("languages", '["English"]')
    if isinstance(languages, list):
        languages = ", ".join(languages)
    elif isinstance(languages, str):
        try:
            parsed = json.loads(languages)
            languages = ", ".join(parsed) if isinstance(parsed, list) else languages
        except (json.JSONDecodeError, TypeError):
            pass

    quirks = supplier_profile.get("quirks", "None noted")
    if isinstance(quirks, list):
        quirks = "\n".join(f"  - {q}" for q in quirks)
    elif isinstance(quirks, str):
        try:
            parsed = json.loads(quirks)
            if isinstance(parsed, list):
                quirks = "\n".join(f"  - {q}" for q in parsed)
        except (json.JSONDecodeError, TypeError):
            pass

    observations = "\n".join(f"  - {o}" for o in pass1_result.observations) if pass1_result.observations else "None"

    prompt = template.replace("{supplier_name}", supplier_name)
    prompt = prompt.replace("{format_type}", format_type)
    prompt = prompt.replace("{languages}", languages)
    prompt = prompt.replace("{quirks}", quirks)
    prompt = prompt.replace("{pass1_observations}", observations)

    return prompt


def run_pass2(client: anthropic.Anthropic, image_b64: str,
              supplier_profile: dict, pass1_result: Pass1Result) -> Pass2Result:
    """Execute Pass 2 Vision API call for one receipt image."""
    prompt = build_pass2_prompt(supplier_profile, pass1_result)

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=PASS2_MAX_TOKENS,
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
    return parse_llm_response(response_text, Pass2Result)
