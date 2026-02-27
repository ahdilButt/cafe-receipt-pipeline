"""
Pydantic models for the 3-pass receipt processing pipeline.

Model hierarchy:
- Pass1Result: Vision API recon output (supplier identification)
- Pass2Result: Vision API extraction output (line items)
- Pass3Result: Text API categorisation output (ingredient matching)
- ProcessedLineItem: Merged Pass2 + Pass3 + conversion data
- ProcessedReceipt: Complete receipt after all passes
- IngredientCost: Aggregated cost data per canonical ingredient
- MenuItemCost: COGS and margin per menu item
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# --- Enums ---

class ImageQuality(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNREADABLE = "unreadable"


class FormatType(str, Enum):
    FORMAL_INVOICE = "formal_invoice"
    THERMAL_RECEIPT = "thermal_receipt"
    HANDWRITTEN = "handwritten"
    OTHER = "other"


class DamageType(str, Enum):
    NONE = "none"
    FADED = "faded"
    TORN = "torn"
    STAINED = "stained"
    SEVERELY_DAMAGED = "severely_damaged"


class ExpenseCategory(str, Enum):
    MENU_INGREDIENT = "menu_ingredient"
    MENU_CONSUMABLE = "menu_consumable"
    OPERATIONAL_FOOD = "operational_food"
    OPERATIONAL_SUPPLY = "operational_supply"
    EQUIPMENT_SERVICE = "equipment_service"
    NON_OPERATIONAL = "non_operational"
    UNKNOWN = "unknown"


# --- Pass 1 Models (Vision -> Recon) ---

class Pass1Result(BaseModel):
    """LLM output from Pass 1: Reconnaissance."""
    supplier_name: Optional[str] = None
    supplier_match_confidence: str = "low"
    supplier_reasoning: str
    invoice_number: Optional[str] = None
    date: Optional[str] = None
    currency: str = "EUR"
    format_type: FormatType
    image_quality: ImageQuality
    damage_type: DamageType = DamageType.NONE
    observations: list[str] = Field(default_factory=list)
    reasoning: str


# --- Pass 2 Models (Vision -> Extraction) ---

class ExtractedLineItem(BaseModel):
    """Single line item as read from the receipt."""
    item_index: int
    raw_description: str
    quantity: Optional[float] = None
    raw_unit: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    pack_size: Optional[int] = None  # "pack of 200" -> 200. Null if not a pack item.
    original_unit_price: Optional[float] = None
    original_line_total: Optional[float] = None
    correction_note: Optional[str] = None
    reading_confidence: str = "high"
    reading_note: Optional[str] = None


class Pass2Result(BaseModel):
    """LLM output from Pass 2: Line item extraction."""
    line_items: list[ExtractedLineItem]
    receipt_subtotal: Optional[float] = None
    receipt_total: Optional[float] = None
    tax_amount: Optional[float] = None
    calculated_sum: float
    sum_matches_total: Optional[bool] = None
    sum_discrepancy_note: Optional[str] = None
    reasoning: str


# --- Pass 3 Models (Text -> Categorisation) ---

class CategorisedItem(BaseModel):
    """Pass 3 output: categorisation for one line item."""
    line_item_index: int
    raw_description: str
    selected_ingredient_id: Optional[str] = None
    expense_category: ExpenseCategory
    is_discrete_consumable: bool = False
    confidence: str = "high"
    reasoning: str


class Pass3Result(BaseModel):
    """LLM output from Pass 3: Categorisation & Matching."""
    categorised_items: list[CategorisedItem]
    reasoning: str


# --- Internal Pipeline Models ---

class ProcessedLineItem(BaseModel):
    """Fully processed line item combining Pass 2 + Pass 3 + conversion."""
    # Pass 2 fields
    raw_description: str
    quantity: Optional[float] = None
    raw_unit: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    currency: str = "EUR"
    original_unit_price: Optional[float] = None
    original_line_total: Optional[float] = None
    correction_note: Optional[str] = None
    # Pass 3 fields
    canonical_ingredient_id: Optional[str] = None
    expense_category: ExpenseCategory = ExpenseCategory.UNKNOWN
    category_reasoning: Optional[str] = None
    match_confidence: Optional[str] = None
    match_reasoning: Optional[str] = None
    # Track B fields (discrete consumables)
    pack_size: Optional[int] = None
    is_discrete_consumable: bool = False
    total_individual_units: Optional[float] = None
    # Conversion fields (computed by code)
    line_total_eur: Optional[float] = None
    base_unit_quantity: Optional[float] = None
    cost_per_base_unit: Optional[float] = None
    conversion_note: Optional[str] = None
    # Flags
    is_flagged: bool = False
    flag_reason: Optional[str] = None


class ProcessedReceipt(BaseModel):
    """Complete receipt after all 3 passes + validation + conversion."""
    receipt_id: str
    filename: str
    invoice_number: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    date: Optional[str] = None
    receipt_total: Optional[float] = None
    currency: str = "EUR"
    receipt_total_eur: Optional[float] = None
    status: str = "pending"
    damage_type: str = "none"
    has_corrections: bool = False
    image_quality: Optional[str] = None
    pass1_reasoning: Optional[str] = None
    pass2_reasoning: Optional[str] = None
    pass3_reasoning: Optional[str] = None
    line_items: list[ProcessedLineItem] = Field(default_factory=list)
    notes: Optional[str] = None


class IngredientCost(BaseModel):
    """Aggregated cost data for one canonical ingredient."""
    ingredient_id: str
    total_spend_eur: float
    total_base_units: float
    weighted_avg_cost: float
    num_receipts: int
    num_line_items: int
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    price_variance_pct: Optional[float] = None


class MenuItemCost(BaseModel):
    """COGS and margin calculation for one menu item."""
    menu_item_id: str
    menu_item_name: str
    category: str
    sell_price: float
    total_cogs: float
    gross_profit: float
    gross_margin_pct: float
    markup_pct: float
    ingredient_breakdown: list[dict]
    missing_ingredients: list[str] = Field(default_factory=list)
