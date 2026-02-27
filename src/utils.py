"""
Shared utilities for the receipt processing pipeline.
"""

import json


def parse_llm_response(response_text: str, model_class):
    """Parse LLM JSON response into a Pydantic model.
    Handles: raw JSON, ```json-fenced JSON, and validation errors."""
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # Remove first line (```json or ```)
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    data = json.loads(text)
    return model_class.model_validate(data)
