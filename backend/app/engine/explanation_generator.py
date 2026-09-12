"""
Explanation Generator Engine
Generates concise, factual, non-technical explanations grounded strictly in
verified financial facts produced by the deterministic engine.
Never invents financial facts, amounts, or dates.
"""

from datetime import date
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

from app.models.financial import UserFinancialProfile, FinancialState, FinancialEvent, EventType, EventStatus
from app.models.requests import PurchaseRequest
from app.utils.date_helpers import parse_date
from app.utils.logger import logger


class ExplanationFacts(BaseModel):
    current_balance: float
    minimum_required_balance: float
    purchase_amount: float
    item_name: str
    affordability_status: str
    recommended_payment_method: str
    earliest_date_for_full_payment: Optional[str] = None
    spending_changes_needed: List[str] = Field(default_factory=list)
    upcoming_expenses_summary: List[str] = Field(default_factory=list)
    upcoming_income_summary: List[str] = Field(default_factory=list)


class ExplanationGenerator:
    """Generates user-friendly explanations from verified deterministic facts."""

    @classmethod
    def extract_facts(
        cls,
        request: PurchaseRequest,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        events: Optional[List[FinancialEvent]] = None,
        as_of_date: Union[str, date] = "2026-09-12",
        decision_payload: Optional[Dict[str, Any]] = None,
    ) -> ExplanationFacts:
        """Extracts structured verified facts from deterministic state and evaluation results."""
        as_of_d = parse_date(as_of_date)

        # 1. Available balance and minimum safety buffer
        if isinstance(start_balance, UserFinancialProfile):
            avail_bal = start_balance.get_total_available_balance()
            min_buf = start_balance.get_total_safety_buffer()
        elif isinstance(start_balance, FinancialState):
            avail_bal = start_balance.available_balance
            min_buf = start_balance.minimum_required_balance
        else:
            avail_bal = float(start_balance)
            min_buf = 1000.0  # Standard default safety buffer

        # 2. Extract key upcoming expenses and confirmed income (next 30 days)
        expenses_summary: List[str] = []
        income_summary: List[str] = []

        if events:
            for evt in events:
                if evt.status in [EventStatus.CANCELLED, EventStatus.FAILED, EventStatus.SUPERSEDED]:
                    continue
                if evt.amount is None or evt.amount <= 0:
                    continue

                evt_d = parse_date(evt.event_date)
                if as_of_d <= evt_d <= as_of_d + timedelta_days(45):
                    cat = (evt.category or "expense").replace("_", " ").lower()
                    amt_str = f"${evt.amount:.2f}"
                    date_str = evt_d.strftime("%Y-%m-%d")

                    if evt.event_type == EventType.EXPENSE:
                        expenses_summary.append(f"{cat} ({amt_str} on {date_str})")
                    elif evt.event_type == EventType.INCOME:
                        income_summary.append(f"salary ({amt_str} on {date_str})" if "salary" in cat or "paycheck" in cat else f"income ({amt_str} on {date_str})")

        # 3. Pull decision payload parameters
        aff_status = decision_payload.get("affordability_status", "not_affordable") if decision_payload else "not_affordable"
        rec_method = decision_payload.get("recommended_payment_method", "not_recommended") if decision_payload else "not_recommended"
        earliest_date = decision_payload.get("earliest_date_for_full_payment") if decision_payload else None
        spending_changes = decision_payload.get("spending_changes_needed", []) if decision_payload else []

        return ExplanationFacts(
            current_balance=round(avail_bal, 2),
            minimum_required_balance=round(min_buf, 2),
            purchase_amount=round(request.full_price, 2),
            item_name=request.item_name or "purchase",
            affordability_status=aff_status,
            recommended_payment_method=rec_method,
            earliest_date_for_full_payment=earliest_date,
            spending_changes_needed=spending_changes,
            upcoming_expenses_summary=expenses_summary[:3],
            upcoming_income_summary=income_summary[:2],
        )

    @classmethod
    def generate_explanation(
        cls,
        request: PurchaseRequest,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        events: Optional[List[FinancialEvent]] = None,
        as_of_date: Union[str, date] = "2026-09-12",
        decision_payload: Optional[Dict[str, Any]] = None,
        use_ai_enhancer: bool = False,
    ) -> str:
        """
        Generates a concise, understandable, non-technical explanation.
        Grounded strictly in verified financial facts.
        """
        facts = cls.extract_facts(
            request=request,
            start_balance=start_balance,
            events=events,
            as_of_date=as_of_date,
            decision_payload=decision_payload,
        )

        explanation = cls._build_template_explanation(facts)

        if use_ai_enhancer:
            explanation = cls._refine_with_ai(facts, explanation)

        return explanation

    @classmethod
    def _build_template_explanation(cls, f: ExplanationFacts) -> str:
        """Builds 100% factual template explanation directly from extracted facts."""
        item = f.item_name
        price = f"${f.purchase_amount:.2f}"
        balance = f"${f.current_balance:.2f}"
        min_bal = f"${f.minimum_required_balance:.2f}"

        # 1. Affordable Now
        if f.affordability_status == "affordable_now":
            return (
                f"Buying {item} today for {price} is financially safe. "
                f"Your available balance of {balance} comfortably covers the purchase while keeping "
                f"your balance above your required minimum of {min_bal}."
            )

        # 2. Affordable with Plan (BNPL / Installments / Partial Payment)
        if f.affordability_status == "affordable_with_plan":
            method_desc = "an installment plan" if f.recommended_payment_method == "installments" else "a partial payment plan"
            return (
                f"Buying {item} upfront today for {price} would drop your balance below your required minimum of {min_bal}. "
                f"However, using {method_desc} keeps your payments spread out safely while maintaining your minimum balance."
            )

        # 3. Affordable Later (Wait or Spending Changes)
        if f.affordability_status == "affordable_later":
            exp_clause = ""
            if f.upcoming_expenses_summary and f.upcoming_income_summary:
                exp_clause = f" because upcoming expenses ({', '.join(f.upcoming_expenses_summary)}) are due before your next confirmed income ({', '.join(f.upcoming_income_summary)})"
            elif f.upcoming_expenses_summary:
                exp_clause = f" because upcoming expenses ({', '.join(f.upcoming_expenses_summary)}) are due"

            if f.spending_changes_needed:
                changes_str = ", ".join(f.spending_changes_needed)
                date_str = f" by {f.earliest_date_for_full_payment}" if f.earliest_date_for_full_payment else ""
                return (
                    f"Buying {item} today would reduce your balance below your required minimum of {min_bal}{exp_clause}. "
                    f"Pausing optional recurring spending ({changes_str}) allows full payment{date_str} while keeping your balance safe."
                )

            date_target = f.earliest_date_for_full_payment or "a future date"
            return (
                f"Buying {item} today would reduce your balance below your required minimum of {min_bal}{exp_clause}. "
                f"Waiting until {date_target} allows the purchase while keeping your balance above the required minimum."
            )

        # 4. Not Affordable
        return (
            f"Buying {item} today for {price} is not recommended because your available balance of {balance} "
            f"cannot cover the purchase without falling below your required minimum balance of {min_bal}."
        )

    @classmethod
    def _refine_with_ai(cls, facts: ExplanationFacts, template_explanation: str) -> str:
        """
        Refines explanation phrasing using Gemini AI while strictly forbidding fact hallucination.
        Provided ONLY verified structured facts.
        """
        try:
            from app.ai.gemini_service import GeminiService
            gemini = GeminiService()
            if not gemini._client:
                return template_explanation

            prompt = (
                f"Rephrase this financial decision summary into 1 or 2 concise, clear, friendly sentences:\n"
                f"Draft: \"{template_explanation}\"\n\n"
                f"STRICT CONSTRAINTS:\n"
                f"- You are provided strictly verified financial facts: Item='{facts.item_name}', Price=${facts.purchase_amount}, Balance=${facts.current_balance}, Minimum Balance=${facts.minimum_required_balance}, Earliest Date='{facts.earliest_date_for_full_payment}'.\n"
                f"- NEVER introduce new financial facts, numbers, dates, or assumptions not present above.\n"
                f"- Keep the explanation concise, understandable, and non-technical."
            )

            from google.genai import types
            config = types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=150,
            )

            res = gemini._client.models.generate_content(
                model=gemini.model,
                contents=prompt,
                config=config,
            )

            if res and res.text:
                cleaned = res.text.strip().replace('"', '')
                if len(cleaned) > 10:
                    return cleaned

        except Exception as e:
            logger.warning(f"AI explanation refinement skipped/failed: {e}")

        return template_explanation


def timedelta_days(days: int):
    from datetime import timedelta
    return timedelta(days=days)
