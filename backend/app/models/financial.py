"""
Financial Data & Account Pydantic Models
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class AccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    CREDIT_CARD = "CREDIT_CARD"
    INVESTMENT_LIQUID = "INVESTMENT_LIQUID"


class EventType(str, Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    TRANSFER = "TRANSFER"
    INVESTMENT_PAYOUT = "INVESTMENT_PAYOUT"
    INVESTMENT_CALL = "INVESTMENT_CALL"


class EventStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ExchangeRate(BaseModel):
    from_currency: str
    to_currency: str = "USD"
    rate: float


class FinancialAccount(BaseModel):
    account_id: str
    type: AccountType
    currency: str = "USD"
    current_balance: float
    credit_limit: Optional[float] = None
    minimum_payment_due: Optional[float] = None
    payment_due_day_of_month: Optional[int] = None


class FinancialEvent(BaseModel):
    event_id: str
    user_id: str
    account_id: str
    event_type: EventType
    status: EventStatus
    amount: Optional[float] = Field(default=None, description="Monetary amount. Must NOT default to 0 if null.")
    currency: str = "USD"
    event_date: str  # YYYY-MM-DD
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None  # WEEKLY, BIWEEKLY, MONTHLY
    category: str
    merchant: Optional[str] = None
    related_event_id: Optional[str] = Field(default=None, description="Links to prior event ID for lifecycle state changes")
    linked_event_id: Optional[str] = Field(default=None, description="Links to external evidence ID (image/message)")


class UserFinancialProfile(BaseModel):
    user_id: str
    accounts: List[FinancialAccount]
    minimum_safety_buffer: float = Field(default=1000.0)
    monthly_gross_income: float = Field(default=0.0)
    base_currency: str = "USD"


class FinancialState(BaseModel):
    user_id: str
    as_of_date: str  # YYYY-MM-DD
    available_balance: float = Field(description="Available liquid cash balance (checking/savings/liquid)")
    minimum_balance_to_keep: float = Field(description="Minimum safety buffer to maintain")
    
    recurring_income: List[FinancialEvent] = Field(default_factory=list)
    total_monthly_recurring_income: float = 0.0
    confirmed_future_income: List[FinancialEvent] = Field(default_factory=list)
    
    recurring_expenses: List[FinancialEvent] = Field(default_factory=list)
    total_monthly_recurring_expenses: float = 0.0
    confirmed_future_expenses: List[FinancialEvent] = Field(default_factory=list)
    
    pending_transactions: List[FinancialEvent] = Field(default_factory=list)
    essential_expenses: List[FinancialEvent] = Field(default_factory=list)
    flexible_expenses: List[FinancialEvent] = Field(default_factory=list)
    
    relevant_investments: List[FinancialEvent] = Field(default_factory=list)
    total_investment_value: float = 0.0
    credit_card_minimum_payments: float = 0.0
    
    base_currency: str = "USD"
