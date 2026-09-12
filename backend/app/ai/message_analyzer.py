"""
Chat & Unstructured Message Analyzer
Parses text logs for expense changes, income updates, transaction cancellations, and dates.
Operates via GeminiService with deterministic regex fallbacks for offline/zero-latency scenarios.
"""

import re
from typing import List, Optional
from app.ai.gemini_service import GeminiService
from app.models.evidence import EvidenceType, ExtractedFact
from app.utils.logger import logger


class MessageAnalyzer:
    """Extracts financial obligations, price changes, and date shifts from text messages."""

    def __init__(self, gemini_service: Optional[GeminiService] = None):
        self.gemini = gemini_service or GeminiService()

    def analyze_message(
        self,
        message_id: str,
        sender: str,
        text: str,
        target_event_id: Optional[str] = None,
    ) -> List[ExtractedFact]:
        """
        Analyzes a message for structured financial facts.
        Uses Gemini API when available, and regex rules as reliable fallback.
        """
        logger.info(f"Analyzing message {message_id} from '{sender}' (target_event_id: {target_event_id})")

        # 1. Primary AI extraction
        ai_facts = self.gemini.extract_facts_from_text(
            text=text,
            source_id=message_id,
            target_event_id=target_event_id,
            source_type=EvidenceType.CHAT_MESSAGE,
        )

        if ai_facts:
            return ai_facts

        # 2. Heuristic / Rule-based fallback if AI produces no facts or is offline
        fallback_facts = self._rule_based_extraction(message_id, text, target_event_id)
        return fallback_facts

    def _rule_based_extraction(
        self,
        message_id: str,
        text: str,
        target_event_id: Optional[str] = None,
    ) -> List[ExtractedFact]:
        """Deterministic regex extraction for offline execution and fast testing."""
        facts: List[ExtractedFact] = []
        lower_text = text.lower()

        # Extract Event ID if present in text (e.g. EVT_123 or EVENT_123)
        evt_match = re.search(r'\b(EVT_\w+|EVENT_\w+)\b', text, re.IGNORECASE)
        resolved_event_id = target_event_id or (evt_match.group(1).upper() if evt_match else None)

        # Detect Cancellation / Settlement
        if any(kw in lower_text for kw in ["cancel", "canceled", "cancelled", "refund", "refunded", "waived", "settled"]):
            facts.append(
                ExtractedFact(
                    fact_id=f"FACT_{message_id}_CANCEL",
                    source_id=message_id,
                    source_type=EvidenceType.CHAT_MESSAGE,
                    source="message",
                    fact_type="cancellation",
                    evidence=text[:150],
                    confidence=0.95,
                    event_id=resolved_event_id,
                    target_event_id=resolved_event_id,
                    details="Detected cancellation/refund keyword in text message.",
                )
            )

        # Extract Amount (e.g., $25,000, 25000 USD, INR 25000, $250.00, €500)
        amount_match = re.search(
            r'(\$|€|£|₹|INR|USD|EUR|GBP|CAD)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|\d+(?:\.\d{1,2})?)\s*(USD|EUR|GBP|INR|CAD)?',
            text,
            re.IGNORECASE,
        )

        extracted_val: Optional[float] = None
        curr = "USD"

        if amount_match:
            raw_val_str = amount_match.group(2).replace(",", "")
            try:
                extracted_val = float(raw_val_str)
                symbol_prefix = (amount_match.group(1) or "").upper().strip()
                symbol_suffix = (amount_match.group(3) or "").upper().strip()

                if "INR" in symbol_prefix or "INR" in symbol_suffix or "₹" in symbol_prefix:
                    curr = "INR"
                elif "EUR" in symbol_prefix or "EUR" in symbol_suffix or "€" in symbol_prefix:
                    curr = "EUR"
                elif "GBP" in symbol_prefix or "GBP" in symbol_suffix or "£" in symbol_prefix:
                    curr = "GBP"
                elif "CAD" in symbol_prefix or "CAD" in symbol_suffix:
                    curr = "CAD"
            except ValueError:
                extracted_val = None

        # Extract YYYY-MM-DD Date
        date_match = re.search(r'\b(20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b', text)
        effective_date = date_match.group(1) if date_match else None

        # Detect Recurring Patterns
        recurrence = None
        if "monthly" in lower_text or "per month" in lower_text or "/mo" in lower_text:
            recurrence = "MONTHLY"
        elif "weekly" in lower_text or "per week" in lower_text or "/wk" in lower_text:
            recurrence = "WEEKLY"
        elif "biweekly" in lower_text or "every 2 weeks" in lower_text:
            recurrence = "BIWEEKLY"

        # Determine fact_type
        if extracted_val is not None:
            fact_type = "amount"
            if "rent" in lower_text or "increase" in lower_text or "raise" in lower_text or "higher" in lower_text:
                fact_type = "expense_increase"
            elif "discount" in lower_text or "lower" in lower_text or "cut" in lower_text or "decrease" in lower_text:
                fact_type = "expense_decrease"
            elif "bonus" in lower_text or "salary" in lower_text or "income" in lower_text:
                fact_type = "income_addition"

            if recurrence:
                fact_type = f"recurring_{'income' if 'income' in fact_type or 'salary' in lower_text else 'expense'}"

            # Uncertainty check
            is_uncert = any(w in lower_text for w in ["maybe", "approx", "roughly", "around", "unclear", "not sure"])
            conf = 0.5 if is_uncert else 0.85

            facts.append(
                ExtractedFact(
                    fact_id=f"FACT_{message_id}_AMT",
                    source_id=message_id,
                    source_type=EvidenceType.CHAT_MESSAGE,
                    source="message",
                    fact_type=fact_type,
                    value=extracted_val,
                    amount=extracted_val,
                    currency=curr,
                    effective_date=effective_date,
                    confidence=conf,
                    evidence=text[:150],
                    event_id=resolved_event_id,
                    target_event_id=resolved_event_id,
                    is_uncertain=is_uncert,
                    recurrence_pattern=recurrence,
                )
            )

        return facts
