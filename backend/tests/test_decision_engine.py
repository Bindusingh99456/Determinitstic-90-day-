"""
Unit tests for Main Decision Engine (DecisionEngine)
Tests:
- Production of exact required decision payload schema
- Four affordability statuses: affordable_now, affordable_with_plan, affordable_later, not_affordable
- Five payment methods: full_payment, partial_payment, installments, wait, not_recommended
- Independent calculation of earliest_date_for_full_payment
- Exact ranking rules application
- Internal decision payload validation
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
from app.models.requests import PurchaseRequest, PaymentOption, PaymentOptionType
from app.engine.decision_engine import DecisionEngine


class TestDecisionEngine(unittest.TestCase):

    def setUp(self):
        self.as_of_date = "2026-09-12"

    def test_1_affordable_now(self):
        """User has $5,000 balance, $1,000 buffer. Wants to buy $800 item upfront."""
        req = PurchaseRequest(
            request_id="REQ_NOW",
            user_id="U1",
            item_name="Smart Watch",
            full_price=800.0,
            payment_options=[PaymentOption(option_id="OPT_UP", type=PaymentOptionType.UPFRONT)],
        )

        output = DecisionEngine.evaluate_request(
            request=req,
            start_balance=5000.0,
            as_of_date=self.as_of_date,
        )

        self.assertEqual(output["request_id"], "REQ_NOW")
        self.assertEqual(output["amount_safe_to_pay"], 800.0)
        self.assertEqual(output["affordability_status"], "affordable_now")
        self.assertEqual(output["recommended_payment_method"], "full_payment")
        self.assertEqual(output["spending_changes_needed"], [])
        self.assertIsNotNone(output["earliest_date_for_full_payment"])
        self.assertTrue(len(output["decision_explanation"]) > 0)

    def test_2_affordable_with_plan(self):
        """
        User balance = $1,300, buffer = $1,000. Upfront $1,000 is UNSAFE (drops balance to $300).
        BNPL installment option available: $250 down payment today, 3 x $250 installments every 14 days.
        Result: affordable_with_plan using 'installments'.
        """
        req = PurchaseRequest(
            request_id="REQ_PLAN",
            user_id="U1",
            item_name="Laptop",
            full_price=1000.0,
            payment_options=[
                PaymentOption(
                    option_id="OPT_BNPL_4X",
                    type=PaymentOptionType.BNPL_INSTALLMENTS,
                    down_payment=250.0,
                    installment_amount=250.0,
                    num_installments=3,
                    frequency_days=14,
                )
            ],
        )

        output = DecisionEngine.evaluate_request(
            request=req,
            start_balance=1300.0,
            as_of_date=self.as_of_date,
        )

        self.assertEqual(output["request_id"], "REQ_PLAN")
        self.assertEqual(output["amount_safe_to_pay"], 300.0)
        self.assertEqual(output["affordability_status"], "affordable_with_plan")
        self.assertEqual(output["recommended_payment_method"], "installments")
        self.assertEqual(output["spending_changes_needed"], [])

    def test_3_affordable_later(self):
        """
        User balance = $1,200, buffer = $1,000. Upfront $800 drops balance to $400 (< $1,000 -> Unsafe).
        Salary of $2,000 arrives on 2026-09-20.
        Result: affordable_later using 'wait' plan.
        """
        events = [
            FinancialEvent(
                event_id="EVT_PAYDAY",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-09-20",
                category="SALARY",
            )
        ]

        req = PurchaseRequest(
            request_id="REQ_WAIT",
            user_id="U1",
            item_name="Television",
            full_price=800.0,
            payment_options=[PaymentOption(option_id="OPT_UP", type=PaymentOptionType.UPFRONT)],
        )

        output = DecisionEngine.evaluate_request(
            request=req,
            start_balance=1200.0,
            events=events,
            as_of_date=self.as_of_date,
        )

        self.assertEqual(output["request_id"], "REQ_WAIT")
        self.assertEqual(output["affordability_status"], "affordable_later")
        self.assertEqual(output["recommended_payment_method"], "wait")
        self.assertEqual(output["earliest_date_for_full_payment"], "2026-09-20")

    def test_4_not_affordable(self):
        """
        User balance = $1,000, buffer = $1,000. Headroom = 0.
        Wants to buy $2,000 item. No income expected.
        Result: not_affordable with recommended_payment_method = 'not_recommended'.
        """
        req = PurchaseRequest(
            request_id="REQ_IMPOSSIBLE",
            user_id="U1",
            item_name="Luxury Trip",
            full_price=2000.0,
            payment_options=[PaymentOption(option_id="OPT_UP", type=PaymentOptionType.UPFRONT)],
        )

        output = DecisionEngine.evaluate_request(
            request=req,
            start_balance=1000.0,
            as_of_date=self.as_of_date,
        )

        self.assertEqual(output["request_id"], "REQ_IMPOSSIBLE")
        self.assertEqual(output["amount_safe_to_pay"], 0.0)
        self.assertEqual(output["affordability_status"], "not_affordable")
        self.assertEqual(output["recommended_payment_method"], "not_recommended")

    def test_5_exact_ranking_rules(self):
        """
        Test ranking rules:
        Option A: $1,000 full price, $100 upfront fee (Total $1,100)
        Option B: $1,000 full price, $0 fee (Total $1,000)
        Option B must be chosen over Option A (Rule 3: Minimize total amount paid).
        """
        req = PurchaseRequest(
            request_id="REQ_RANKING",
            user_id="U1",
            item_name="Gadget",
            full_price=1000.0,
            payment_options=[
                PaymentOption(option_id="OPT_EXPENSIVE", type=PaymentOptionType.UPFRONT, upfront_fee=100.0),
                PaymentOption(option_id="OPT_CHEAP", type=PaymentOptionType.UPFRONT, upfront_fee=0.0),
            ],
        )

        output = DecisionEngine.evaluate_request(
            request=req,
            start_balance=5000.0,
            as_of_date=self.as_of_date,
        )

        self.assertEqual(output["affordability_status"], "affordable_now")
        self.assertEqual(output["payment_plan"]["option_id"], "OPT_CHEAP")

    def test_6_internal_validation_failure_detection(self):
        """Verifies validate_decision_payload raises ValueError on invalid payload."""
        invalid_payload = {
            "request_id": "REQ_ERR",
            "amount_safe_to_pay": 500.0,
            "affordability_status": "affordable_now",
            "recommended_payment_method": "wait",  # INVALID! affordable_now requires full_payment
            "payment_plan": {},
            "earliest_date_for_full_payment": "2026-09-12",
            "spending_changes_needed": [],
            "decision_explanation": "Test error",
        }

        with self.assertRaises(ValueError) as context:
            DecisionEngine.validate_decision_payload(invalid_payload, full_price=500.0)
        self.assertIn("affordable_now requires recommended_payment_method = 'full_payment'", str(context.exception))


if __name__ == "__main__":
    unittest.main()
