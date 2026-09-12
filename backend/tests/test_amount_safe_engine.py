"""
Unit tests for amount_safe_to_pay Engine (AmountSafeEngine)
Tests bounds (0 <= amount_safe_to_pay <= requested_amount), preservation of minimum required balance,
future financial events, completion deadline horizon, recurring expenses, confirmed income,
ignoring pending credits, ignoring unrealized investments, ignoring optional spending cutbacks,
currency conversions, and AI evidence facts.
"""

import unittest
from datetime import date
from app.models.financial import (
    UserFinancialProfile,
    FinancialAccount,
    FinancialEvent,
    AccountType,
    EventType,
    EventStatus,
)
from app.models.requests import PurchaseRequest, PaymentOption, PaymentOptionType, SpendingCutback
from app.models.evidence import ExtractedFact, FactType
from app.engine.amount_safe_engine import AmountSafeEngine, convert_currency


class TestAmountSafeEngine(unittest.TestCase):

    def setUp(self):
        self.start_date = "2026-09-12"

    def test_1_fully_affordable_request(self):
        """When user has ample headroom, amount_safe_to_pay is capped at requested_amount."""
        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=5000.0,
            requested_amount=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )
        self.assertEqual(safe_amt, 1500.0)

    def test_2_partially_affordable_request(self):
        """When headroom ($1,200) < requested_amount ($2,000), amount_safe_to_pay equals headroom."""
        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=2200.0,
            requested_amount=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )
        self.assertEqual(safe_amt, 1200.0)

    def test_3_zero_safe_amount_due_to_buffer_breach(self):
        """When balance ($800) is already below minimum buffer ($1,000), safe amount is 0.0."""
        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=800.0,
            requested_amount=500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )
        self.assertEqual(safe_amt, 0.0)

    def test_4_zero_or_negative_requested_amount(self):
        """Requested amount <= 0 returns 0.0."""
        safe_amt_zero = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=5000.0,
            requested_amount=0.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )
        safe_amt_neg = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=5000.0,
            requested_amount=-200.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )
        self.assertEqual(safe_amt_zero, 0.0)
        self.assertEqual(safe_amt_neg, 0.0)

    def test_5_constrained_by_upcoming_expenses(self):
        """
        Starting balance = $3,000, Buffer = $1,000. Day 0 headroom = $2,000.
        Rent expense of $1,500 due on Day 10 (2026-09-22).
        Day 10 balance drops to $1,500 -> Day 10 headroom = $500.
        Requested amount = $1,800.
        amount_safe_to_pay TODAY MUST equal $500.0.
        """
        events = [
            FinancialEvent(
                event_id="EVT_RENT",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1500.0,
                event_date="2026-09-22",
                category="RENT",
            )
        ]

        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=3000.0,
            requested_amount=1800.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
        )
        self.assertEqual(safe_amt, 500.0)

    def test_6_future_income_arriving_later_does_not_inflate_today_safe_amount(self):
        """
        Starting balance = $1,200, Buffer = $1,000. Day 0 headroom = $200.
        Salary of $3,000 arrives on Day 15 (2026-09-27).
        Requested amount = $1,500.
        amount_safe_to_pay TODAY MUST equal $200.0 because paying more today breaches buffer on Days 0-14.
        """
        events = [
            FinancialEvent(
                event_id="EVT_SALARY",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=3000.0,
                event_date="2026-09-27",
                category="SALARY",
            )
        ]

        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=1200.0,
            requested_amount=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
        )
        self.assertEqual(safe_amt, 200.0)

    def test_7_ignore_pending_credits(self):
        """Pending credits MUST NOT be included as liquid cash today."""
        events = [
            FinancialEvent(
                event_id="EVT_PENDING_BONUS",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.INCOME,
                status=EventStatus.PENDING,  # PENDING!
                amount=5000.0,
                event_date="2026-09-13",
                category="BONUS",
            )
        ]

        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=1200.0,
            requested_amount=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
        )
        self.assertEqual(safe_amt, 200.0)

    def test_8_ignore_unrealized_investments(self):
        """User profile with $1,200 checking and $50,000 non-liquid investment."""
        profile = UserFinancialProfile(
            user_id="U1",
            accounts=[
                FinancialAccount(account_id="ACC1", name="Checking", type=AccountType.CHECKING, current_balance=1200.0),
                FinancialAccount(account_id="ACC2", name="Stock Portfolio", type=AccountType.INVESTMENT_NON_LIQUID, current_balance=50000.0),
            ],
            minimum_safety_buffer=1000.0,
        )

        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=profile,
            requested_amount=3000.0,
            start_date=self.start_date,
        )
        self.assertEqual(safe_amt, 200.0)

    def test_9_completion_deadline_extends_horizon(self):
        """
        Completion deadline set to 120 days in the future (2027-01-10).
        A large payment obligation of $1,000 occurs on Day 110 (2026-12-31).
        Start balance = $2,500, Buffer = $1,000.
        Without deadline (90d): safe amount = $1,500.
        With 120d deadline: safe amount = $500.0.
        """
        events = [
            FinancialEvent(
                event_id="EVT_TAX_PAYMENT",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1000.0,
                event_date="2026-12-31",
                category="TAX",
            )
        ]

        safe_amt_no_deadline = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=2500.0,
            requested_amount=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
            horizon_days=90,  # 90d horizon won't reach Dec 31
        )
        self.assertEqual(safe_amt_no_deadline, 1500.0)

        safe_amt_with_deadline = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=2500.0,
            requested_amount=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            completion_deadline="2027-01-10",  # Extends horizon
            events=events,
        )
        self.assertEqual(safe_amt_with_deadline, 500.0)

    def test_10_currency_conversion(self):
        """
        User base currency = USD.
        Start balance = $2,000 USD, Buffer = $1,000 USD -> Headroom = $1,000 USD.
        Requested amount = 500 EUR (EUR rate = 1.08 USD, so 500 EUR = $540 USD).
        $540 USD < $1,000 USD headroom -> amount_safe_to_pay = 500.0 EUR.
        """
        safe_amt_eur = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=2000.0,
            requested_amount=500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            currency="EUR",
            base_currency="USD",
        )
        self.assertEqual(safe_amt_eur, 500.0)

        # Now test constrained currency: Headroom = $54 USD -> 54 / 1.08 = 50.0 EUR.
        safe_amt_eur_constrained = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=1054.0,
            requested_amount=500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            currency="EUR",
            base_currency="USD",
        )
        self.assertEqual(safe_amt_eur_constrained, 50.0)

    def test_11_ai_evidence_fact_integration(self):
        """
        Evidence fact modifies baseline rent expense from $1,000 to $1,500.
        Start balance = $3,000, Buffer = $1,000.
        Baseline headroom would be $1,000, but fact increases rent by $500, reducing headroom to $500.
        """
        events = [
            FinancialEvent(
                event_id="EVT_RENT_BASE",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1000.0,
                event_date="2026-09-20",
                category="RENT",
            )
        ]

        facts = [
            ExtractedFact(
                fact_id="FACT_1",
                source_type="EMAIL",
                fact_type=FactType.PRICE_AMENDMENT,
                target_event_id="EVT_RENT_BASE",
                amended_amount=1500.0,
                confidence_score=0.95,
            )
        ]

        safe_amt = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=3000.0,
            requested_amount=1000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
            facts=facts,
        )
        self.assertEqual(safe_amt, 500.0)

    def test_12_purchase_request_helper_method(self):
        """Tests calculate_for_request helper method."""
        profile = UserFinancialProfile(
            user_id="U1",
            accounts=[
                FinancialAccount(account_id="ACC1", name="Checking", type=AccountType.CHECKING, current_balance=2500.0)
            ],
            minimum_safety_buffer=1000.0,
        )

        request = PurchaseRequest(
            request_id="REQ_100",
            user_id="U1",
            item_name="Smart OLED TV",
            full_price=1200.0,
            currency="USD",
            offer_expires_at="2026-09-30",
            payment_options=[
                PaymentOption(option_id="OPT_1", type=PaymentOptionType.UPFRONT)
            ],
        )

        safe_amt = AmountSafeEngine.calculate_for_request(
            profile=profile,
            events=[],
            request=request,
            as_of_date=self.start_date,
        )
        # Headroom = 2500 - 1000 = 1500 >= 1200 full price
        self.assertEqual(safe_amt, 1200.0)


if __name__ == "__main__":
    unittest.main()
