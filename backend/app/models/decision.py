"""
Decision & Evaluation Output Pydantic Models for Stitch REST API
"""

from enum import Enum
from typing import List, Optional, Any, Union, Dict
from pydantic import BaseModel, Field
from app.models.evidence import ExtractedFact


class RecommendationType(str, Enum):
    BUY_NOW_UPFRONT = "BUY_NOW_UPFRONT"
    BUY_NOW_PAYMENT_PLAN = "BUY_NOW_PAYMENT_PLAN"
    WAIT = "WAIT"
    REJECT = "REJECT"


class AffordabilityStatus(str, Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class ViolationType(str, Enum):
    SAFETY_BUFFER_BREACH = "SAFETY_BUFFER_BREACH"
    NEGATIVE_CASH_BREACH = "NEGATIVE_CASH_BREACH"
    DTI_CEILING_EXCEEDED = "DTI_CEILING_EXCEEDED"
    UNRESOLVED_MISSING_AMOUNT = "UNRESOLVED_MISSING_AMOUNT"


class StitchDecisionRequest(BaseModel):
    product: Optional[str] = Field(default=None, description="Item or product name")
    item_name: Optional[str] = Field(default=None, description="Alternative field for product name")
    amount: Optional[float] = Field(default=None, ge=0.0, description="Purchase price / requested amount")
    full_price: Optional[float] = Field(default=None, ge=0.0, description="Alternative field for price")
    desired_date: Optional[str] = Field(default=None, description="Desired date or deadline YYYY-MM-DD")
    offer_expires_at: Optional[str] = Field(default=None, description="Alternative field for deadline")
    user_id: str = Field(default="USER_DEFAULT", description="Target user ID")
    request_id: Optional[str] = Field(default=None, description="Optional custom request ID")


class StitchDecisionResponse(BaseModel):
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: Union[str, Dict[str, Any], List[Any]]
    earliest_date_for_full_payment: Optional[str] = None
    spending_changes_needed: Union[str, List[str]]
    decision_explanation: str


class EvaluationOption(BaseModel):
    option_id: str
    option_name: str
    is_safe: bool
    violation_type: Optional[ViolationType] = None
    violation_day: Optional[int] = None
    minimum_projected_balance: float
    total_effective_cost: float


class DecisionSummary(BaseModel):
    recommendation: RecommendationType
    recommended_option_id: Optional[str] = None
    optimal_wait_days: int = Field(default=0)
    recommended_execution_date: str  # YYYY-MM-DD
    summary_reason: str


class FinancialMetrics(BaseModel):
    current_liquid_balance: float
    projected_90d_min_balance_if_purchased_now: float
    projected_90d_min_balance_if_recommended_plan: float
    required_safety_buffer: float
    current_monthly_debt_service: float
    post_purchase_monthly_dti: float


class DecisionResponse(BaseModel):
    request_id: str
    user_id: str
    timestamp: str
    decision: DecisionSummary
    metrics: FinancialMetrics
    evaluated_options: List[EvaluationOption]
    extracted_evidence_facts: List[ExtractedFact] = Field(default_factory=list)
