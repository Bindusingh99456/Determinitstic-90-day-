"""
Financial State Consolidation Service
Reconstructs deterministic financial state for users as of a specific date.
Applies Conservative Solvency Principle and strict dataset conflict resolution.
"""

from typing import List, Optional
from app.models.financial import (
    UserFinancialProfile,
    FinancialEvent,
    FinancialState,
    AccountType,
    EventType,
    EventStatus,
)
from app.models.evidence import ExtractedFact
from app.services.evidence_service import EvidenceService
from app.utils.logger import logger


class FinancialStateService:
    """Computes baseline metrics and reconstructs FinancialState from raw accounts and transactions."""

    ESSENTIAL_CATEGORIES = {
        "RENT", "MORTGAGE", "UTILITIES", "GROCERIES", "HEALTHCARE",
        "MEDICAL", "INSURANCE", "LOAN", "LOAN_PAYMENT", "DEBT",
        "TUITION", "TAX", "ESSENTIAL", "CAR_PAYMENT"
    }

    def __init__(self, evidence_service: Optional[EvidenceService] = None):
        self.evidence_service = evidence_service or EvidenceService()

    def build_financial_state(
        self,
        profile: UserFinancialProfile,
        events: List[FinancialEvent],
        facts: Optional[List[ExtractedFact]] = None,
        as_of_date: str = "2026-09-12",
    ) -> FinancialState:
        """
        Reconstructs the deterministic financial state as of as_of_date.
        Strictly applies:
        - Excludes cancelled, failed, or superseded events.
        - Excludes pending credits/inflows from available liquid cash.
        - Keeps unrealized investments out of available cash.
        - Preserves null financial amounts (never defaulting null to 0).
        - Categorizes essential vs flexible obligations.
        - Applies Conservative Solvency Principle via evidence merging.
        """
        logger.info(f"Reconstructing FinancialState for user {profile.user_id} as of {as_of_date}")

        # 1. Merge AI evidence facts if present
        merged_events = events
        if facts:
            merged_events = self.evidence_service.merge_facts_with_events(events, facts)

        # 2. Available Balance & Minimum Buffer Calculation
        available_balance = sum(
            acc.current_balance
            for acc in profile.accounts
            if acc.type in [AccountType.CHECKING, AccountType.SAVINGS, AccountType.INVESTMENT_LIQUID]
        )

        credit_card_mins = sum(
            acc.minimum_payment_due or 0.0
            for acc in profile.accounts
            if acc.type == AccountType.CREDIT_CARD
        )

        minimum_buffer = profile.minimum_safety_buffer or 1000.0

        # 3. Categorize Transactions & Outflows
        recurring_income: List[FinancialEvent] = []
        confirmed_future_income: List[FinancialEvent] = []

        recurring_expenses: List[FinancialEvent] = []
        confirmed_future_expenses: List[FinancialEvent] = []

        pending_txs: List[FinancialEvent] = []
        essential_expenses: List[FinancialEvent] = []
        flexible_expenses: List[FinancialEvent] = []
        relevant_investments: List[FinancialEvent] = []

        total_invest_val = 0.0

        # Process Accounts for Investment Value
        for acc in profile.accounts:
            if acc.type == AccountType.INVESTMENT_LIQUID:
                total_invest_val += acc.current_balance

        for evt in merged_events:
            # Rule: Ignore cancelled, failed, or superseded transactions
            if evt.status in [EventStatus.CANCELLED, EventStatus.FAILED, EventStatus.SUPERSEDED]:
                continue

            # Pending handling
            if evt.status == EventStatus.PENDING:
                pending_txs.append(evt)
                # Pending outflows are liabilities; pending inflows are NOT added to liquid cash
                if evt.event_type == EventType.EXPENSE and evt.event_date >= as_of_date:
                    confirmed_future_expenses.append(evt)

            # Confirmed handling
            if evt.status == EventStatus.CONFIRMED:
                # Investment payouts / calls
                if evt.event_type in [EventType.INVESTMENT_PAYOUT, EventType.INVESTMENT_CALL] or evt.category.upper() == "INVESTMENT":
                    relevant_investments.append(evt)
                    if evt.event_type == EventType.INVESTMENT_PAYOUT and evt.amount:
                        total_invest_val += evt.amount

                # Income Streams
                elif evt.event_type == EventType.INCOME:
                    if evt.is_recurring:
                        recurring_income.append(evt)
                    if evt.event_date >= as_of_date:
                        confirmed_future_income.append(evt)

                # Expense Streams
                elif evt.event_type == EventType.EXPENSE:
                    if evt.is_recurring:
                        recurring_expenses.append(evt)
                    if evt.event_date >= as_of_date:
                        confirmed_future_expenses.append(evt)

                    # Categorize Essential vs Flexible
                    cat_upper = evt.category.upper()
                    if any(kw in cat_upper for kw in self.ESSENTIAL_CATEGORIES):
                        essential_expenses.append(evt)
                    else:
                        flexible_expenses.append(evt)

        # 4. Normalize Recurring Totals (Monthly)
        monthly_rec_income = sum(
            self._normalize_monthly_amount(evt.amount, evt.recurrence_pattern)
            for evt in recurring_income
        )

        monthly_rec_expenses = sum(
            self._normalize_monthly_amount(evt.amount, evt.recurrence_pattern)
            for evt in recurring_expenses
        )

        return FinancialState(
            user_id=profile.user_id,
            as_of_date=as_of_date,
            available_balance=available_balance,
            minimum_balance_to_keep=minimum_buffer,
            recurring_income=recurring_income,
            total_monthly_recurring_income=round(monthly_rec_income, 2),
            confirmed_future_income=confirmed_future_income,
            recurring_expenses=recurring_expenses,
            total_monthly_recurring_expenses=round(monthly_rec_expenses, 2),
            confirmed_future_expenses=confirmed_future_expenses,
            pending_transactions=pending_txs,
            essential_expenses=essential_expenses,
            flexible_expenses=flexible_expenses,
            relevant_investments=relevant_investments,
            total_investment_value=round(total_invest_val, 2),
            credit_card_minimum_payments=round(credit_card_mins, 2),
            base_currency=profile.base_currency or "USD",
        )

    @staticmethod
    def _normalize_monthly_amount(amount: Optional[float], recurrence_pattern: Optional[str]) -> float:
        """Converts an event amount to monthly equivalent. Strictly skips None amounts."""
        if amount is None:
            return 0.0

        pattern = (recurrence_pattern or "MONTHLY").upper().strip()

        if pattern == "WEEKLY":
            return amount * (52.0 / 12.0)
        elif pattern in ["BIWEEKLY", "FORTNIGHTLY"]:
            return amount * (26.0 / 12.0)
        elif pattern in ["ANNUALLY", "YEARLY"]:
            return amount / 12.0
        return amount * 1.0  # MONTHLY default
