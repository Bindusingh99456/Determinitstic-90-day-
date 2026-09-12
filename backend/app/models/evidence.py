"""
Unstructured Evidence & Fact Extraction Pydantic Models
"""

from enum import Enum
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    CHAT_MESSAGE = "CHAT_MESSAGE"
    RECEIPT_IMAGE = "RECEIPT_IMAGE"
    PAYSTUB_IMAGE = "PAYSTUB_IMAGE"
    LEASE_DOCUMENT = "LEASE_DOCUMENT"
    INVOICE_QUOTE = "INVOICE_QUOTE"


class ExtractedFactType(str, Enum):
    EXPENSE_INCREASE = "EXPENSE_INCREASE"
    EXPENSE_DECREASE = "EXPENSE_DECREASE"
    INCOME_ADDITION = "INCOME_ADDITION"
    INCOME_DELAY = "INCOME_DELAY"
    ONE_TIME_OUTFLOW = "ONE_TIME_OUTFLOW"


class ChatMessage(BaseModel):
    message_id: str
    user_id: str
    sender: str
    timestamp: str
    content_text: str
    associated_event_id: Optional[str] = None
    associated_image_id: Optional[str] = None


class ImageRecord(BaseModel):
    image_id: str
    user_id: str
    file_path_or_url: str
    image_type: EvidenceType
    uploaded_at: str
    linked_event_id: Optional[str] = None


class ExtractedFact(BaseModel):
    fact_id: str
    source_id: str
    source_type: EvidenceType = EvidenceType.CHAT_MESSAGE
    source: str = "message"  # "message", "image", "document"
    fact_type: str = Field(
        ...,
        description="Type of fact: 'amount', 'expense_increase', 'expense_decrease', 'income_addition', 'income_delay', 'cancellation', 'settlement', 'amendment', 'recurring_expense', 'recurring_income', 'event_clarification'"
    )
    value: Optional[float] = Field(default=None, description="Extracted numeric value or amount")
    amount: Optional[float] = Field(default=None, description="Alias for value")
    currency: str = "USD"
    effective_date: Optional[str] = Field(default=None, description="Relevant YYYY-MM-DD date if stated")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Extraction confidence score 0.0 to 1.0")
    evidence: str = Field(default="", description="Exact textual evidence or snippet extracted")
    extracted_text_snippet: str = Field(default="", description="Alias for evidence")
    event_id: Optional[str] = Field(default=None, description="Associated event ID if resolving/updating an event")
    target_event_id: Optional[str] = Field(default=None, description="Alias for event_id")
    is_uncertain: bool = Field(default=False, description="Flagged true if evidence is ambiguous or uncertain")
    recurrence_pattern: Optional[str] = Field(default=None, description="E.g. 'MONTHLY', 'BIWEEKLY', 'WEEKLY' if explicitly stated")
    details: Optional[str] = Field(default=None, description="Additional context or notes extracted from evidence")

    def model_post_init(self, __context: Any) -> None:
        """Sync aliases if one is provided and the other is empty."""
        if self.value is not None and self.amount is None:
            self.amount = self.value
        elif self.amount is not None and self.value is None:
            self.value = self.amount

        if self.evidence and not self.extracted_text_snippet:
            self.extracted_text_snippet = self.evidence
        elif self.extracted_text_snippet and not self.evidence:
            self.evidence = self.extracted_text_snippet

        if self.event_id and not self.target_event_id:
            self.target_event_id = self.event_id
        elif self.target_event_id and not self.event_id:
            self.event_id = self.target_event_id
