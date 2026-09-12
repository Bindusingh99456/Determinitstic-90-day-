"""
Purchase Request & Payment Option Pydantic Models
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class PaymentOptionType(str, Enum):
    UPFRONT = "UPFRONT"
    BNPL_INSTALLMENTS = "BNPL_INSTALLMENTS"
    CREDIT_CARD = "CREDIT_CARD"
    PARTIAL = "PARTIAL"
    WAIT = "WAIT"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class PaymentOption(BaseModel):
    option_id: str
    type: PaymentOptionType
    down_payment: float = Field(default=0.0)
    installment_amount: float = Field(default=0.0)
    num_installments: int = Field(default=1)
    frequency_days: int = Field(default=30)
    upfront_fee: float = Field(default=0.0)
    apr_percent: float = Field(default=0.0)
    allows_partial_payment: bool = Field(default=False)


class SpendingCutback(BaseModel):
    cutback_id: str
    description: str
    monthly_savings: float
    effective_start_date: str  # YYYY-MM-DD


class PurchaseRequest(BaseModel):
    request_id: str
    user_id: str
    item_name: str
    full_price: float
    currency: str = "USD"
    merchant: Optional[str] = None
    category: str = "DISCRETIONARY"
    offer_expires_at: Optional[str] = None
    price_after_expiration: Optional[float] = None
    allows_partial_payment: bool = Field(default=False)
    user_accepts_partial_payment: bool = Field(default=False)
    payment_options: List[PaymentOption]
    user_cutbacks: List[SpendingCutback] = Field(default_factory=list)


class PaymentPlan(BaseModel):
    plan_id: str
    method: PaymentMethod
    option_id: Optional[str] = None
    description: str
    total_payable_amount: float
    financing_fees: float = Field(default=0.0)
    payment_dates: List[str] = Field(default_factory=list)
    payment_amounts: List[float] = Field(default_factory=list)
    schedule: List[tuple] = Field(default_factory=list)  # (date_str, amount, description)
    is_safe: bool = True
    is_valid: bool = True
    rejection_reasons: List[str] = Field(default_factory=list)
    minimum_projected_balance: float = 0.0
    completion_date: str
    violates_completion_deadline: bool = False
