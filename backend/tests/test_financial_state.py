"""
Unit tests for Financial State Engine (FinancialStateService)
Validates conflict resolution rules, available balance math, conservative solvency, and transaction filtering.
"""

import unittest
from app.models.financial import (
    UserFinancialProfile,
    FinancialAccount,
    FinancialEvent,
    AccountType,
    EventType,
    EventStatus,
)
from app.models.evidence import ExtractedFact, EvidenceType
from app.services.financial_state_service import FinancialStateService
from app.services.evidence_service import EvidenceService


class TestFinancialStateEngine(unittest.TestCase):

    def setUp(self):
        self.evidence_service = EvidenceService()
        self.state_service = FinancialStateService(evidence_service=self.evidence_service)

    def test_available_balance_calculation_excludes_pending_credits_and_investments(self):
        """
        MANDATE:
        - Do NOT treat pending credits as available cash.
        - Do NOT treat unrealized investments as cash.
        - Do NOT treat failed/cancelled transactions as active.
        """
        profile = UserFinancialProfile(
            user_id="USER_501",
            accounts=[
                FinancialAccount(account_id="ACC_CHECKING", type=AccountType.CHECKING, current_balance=2500.0),
                FinancialAccount(account_id="ACC_SAVINGS", type=AccountType.SAVINGS, current_balance=5000.0),
                FinancialAccount(account_id="ACC_CREDIT", type=AccountType.CREDIT_CARD, current_balance=-800.0, minimum_payment_due=50.0),
            ],
            minimum_safety_buffer=1000.0,
        )

        events = [
            # Pending credit (MUST NOT be added to liquid balance!)
            FinancialEvent(
                event_id="EVT_PENDING_CREDIT",
                user_id="USER_501",
                account_id="ACC_CHECKING",
                event_type=EventType.INCOME,
                status=EventStatus.PENDING,
                amount=1000.0,
                event_date="2026-09-15",
                category="BONUS",
            ),
            # Failed expense (MUST BE IGNORED)
            FinancialEvent(
                event_id="EVT_FAILED_EXPENSE",
                user_id="USER_501",
                account_id="ACC_CHECKING",
                event_type=EventType.EXPENSE,
                status=EventStatus.FAILED,
                amount=500.0,
                event_date="2026-09-01",
                category="SHOPPING",
            ),
            # Cancelled rent (MUST BE IGNORED)
            FinancialEvent(
                event_id="EVT_CANCELLED_RENT",
                user_id="USER_501",
                account_id="ACC_CHECKING",
                event_type=EventType.EXPENSE,
                status=EventStatus.CANCELLED,
                amount=1200.0,
                event_date="2026-09-01",
                category="RENT",
            ),
            # Confirmed Recurring Expense
            FinancialEvent(
                event_id="EVT_CONFIRMED_RENT",
                user_id="USER_501",
                account_id="ACC_CHECKING",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1500.0,
                event_date="2026-09-15",
                is_recurring=True,
                recurrence_pattern="MONTHLY",
                category="RENT",
            ),
        ]

        state = self.state_service.build_financial_state(profile, events, as_of_date="2026-09-12")

        # Liquid balance = Checking (2500) + Savings (5000) = 7500. (Pending credit 1000 is ignored!)
        self.assertEqual(state.available_balance, 7500.0)
        self.assertEqual(state.credit_card_minimum_payments, 50.0)
        self.assertEqual(state.minimum_balance_to_keep, 1000.0)
        self.assertEqual(len(state.pending_transactions), 1)
        self.assertEqual(state.pending_transactions[0].event_id, "EVT_PENDING_CREDIT")

    def test_conflict_resolution_cancellation_and_conservative_solvency(self):
        """
        1. Explicit cancellation has priority over active status.
        2. Conservative solvency: Choose higher expense when fact amends an expense.
        """
        profile = UserFinancialProfile(
            user_id="USER_502",
            accounts=[
                FinancialAccount(account_id="ACC_CHECKING", type=AccountType.CHECKING, current_balance=3000.0)
            ],
        )

        events = [
            FinancialEvent(
                event_id="EVT_UTILITIES",
                user_id="USER_502",
                account_id="ACC_CHECKING",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=100.0,
                event_date="2026-09-20",
                category="UTILITIES",
            ),
            FinancialEvent(
                event_id="EVT_GYM",
                user_id="USER_502",
                account_id="ACC_CHECKING",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=50.0,
                event_date="2026-09-25",
                category="ENTERTAINMENT",
            ),
        ]

        facts = [
            # Fact 1: Cancel Gym membership
            ExtractedFact(
                fact_id="FACT_CANCEL_GYM",
                source_id="MSG_001",
                source_type=EvidenceType.CHAT_MESSAGE,
                fact_type="cancellation",
                target_event_id="EVT_GYM",
                confidence=0.95,
            ),
            # Fact 2: Increase utility bill due to rate hike
            ExtractedFact(
                fact_id="FACT_UTILITIES_HIKE",
                source_id="MSG_002",
                source_type=EvidenceType.CHAT_MESSAGE,
                fact_type="expense_increase",
                value=180.0,
                target_event_id="EVT_UTILITIES",
                confidence=0.90,
            ),
        ]

        state = self.state_service.build_financial_state(profile, events, facts=facts, as_of_date="2026-09-12")

        # Gym event should be cancelled and excluded from confirmed future expenses
        future_event_ids = [e.event_id for e in state.confirmed_future_expenses]
        self.assertNotIn("EVT_GYM", future_event_ids)
        self.assertIn("EVT_UTILITIES", future_event_ids)

        # Utility expense updated to 180.0 (higher expense per Conservative Solvency Principle)
        utilities_evt = next(e for e in state.confirmed_future_expenses if e.event_id == "EVT_UTILITIES")
        self.assertEqual(utilities_evt.amount, 180.0)

    def test_essential_vs_flexible_categorization(self):
        profile = UserFinancialProfile(
            user_id="USER_503",
            accounts=[FinancialAccount(account_id="ACC_1", type=AccountType.CHECKING, current_balance=4000.0)],
        )

        events = [
            FinancialEvent(
                event_id="EVT_RENT",
                user_id="USER_503",
                account_id="ACC_1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1200.0,
                event_date="2026-09-15",
                category="RENT",
            ),
            FinancialEvent(
                event_id="EVT_DINING",
                user_id="USER_503",
                account_id="ACC_1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=150.0,
                event_date="2026-09-18",
                category="DINING_OUT",
            ),
        ]

        state = self.state_service.build_financial_state(profile, events, as_of_date="2026-09-12")

        essential_ids = [e.event_id for e in state.essential_expenses]
        flexible_ids = [e.event_id for e in state.flexible_expenses]

        self.assertIn("EVT_RENT", essential_ids)
        self.assertIn("EVT_DINING", flexible_ids)

    def test_blank_amount_preserved_never_zeroed(self):
        """Events with null amount must NOT have amount silently converted to 0.0."""
        profile = UserFinancialProfile(
            user_id="USER_504",
            accounts=[FinancialAccount(account_id="ACC_1", type=AccountType.CHECKING, current_balance=2000.0)],
        )

        events = [
            FinancialEvent(
                event_id="EVT_NULL_BILL",
                user_id="USER_504",
                account_id="ACC_1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=None,  # Blank / null
                event_date="2026-09-25",
                is_recurring=True,
                recurrence_pattern="MONTHLY",
                category="UTILITIES",
            )
        ]

        state = self.state_service.build_financial_state(profile, events, as_of_date="2026-09-12")

        # The event model itself must maintain amount as None
        rec_evt = state.recurring_expenses[0]
        self.assertIsNone(rec_evt.amount)


if __name__ == "__main__":
    unittest.main()
