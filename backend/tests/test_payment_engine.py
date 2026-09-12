"""
Unit tests for Payment Plan Engine (PaymentEngine)
Tests all supported payment methods:
- full_payment
- partial_payment (all exact challenge rules)
- installments (financing fees, schedule generation, safety)
- wait (execution date, completion deadline)
- not_recommended (rejection of unsafe/invalid plans)
Also tests CSV reading from request_payment_options.csv / payment_options.csv.
"""

import unittest
import os
import tempfile
import pandas as pd
from datetime import date, timedelta
from app.models.financial import (
    UserFinancialProfile,
    FinancialAccount,
    FinancialEvent,
    AccountType,
    EventType,
    EventStatus,
)
from app.models.requests import (
    PurchaseRequest,
    PaymentOption,
    PaymentOptionType,
    PaymentMethod,
    PaymentPlan,
)
from app.engine.payment_engine import PaymentEngine


class TestPaymentEngine(unittest.TestCase):

    def setUp(self):
        self.start_date = "2026-09-12"

    def test_1_full_payment_safe(self):
        """Full upfront payment when balance ($3,000) is well above safety buffer ($1,000)."""
        req = PurchaseRequest(
            request_id="REQ_1",
            user_id="U1",
            item_name="Camera",
            full_price=1000.0,
            payment_options=[PaymentOption(option_id="OPT_UP", type=PaymentOptionType.UPFRONT)],
        )

        plan = PaymentEngine.evaluate_full_payment(
            requested_amount=1000.0,
            start_balance=3000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        self.assertTrue(plan.is_safe)
        self.assertTrue(plan.is_valid)
        self.assertEqual(plan.method, PaymentMethod.FULL_PAYMENT)
        self.assertEqual(plan.total_payable_amount, 1000.0)
        self.assertEqual(plan.payment_dates, ["2026-09-12"])
        self.assertEqual(plan.payment_amounts, [1000.0])

    def test_2_full_payment_unsafe(self):
        """Full upfront payment when balance ($1,500) drops below safety buffer ($1,000) upon paying $800."""
        plan = PaymentEngine.evaluate_full_payment(
            requested_amount=800.0,
            start_balance=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        self.assertFalse(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)
        self.assertTrue(len(plan.rejection_reasons) > 0)

    def test_3_installments_with_financing_fees(self):
        """
        BNPL plan: Downpayment = $200, Upfront Fee = $20.
        3 installments of $300 every 30 days.
        Total payable = $200 + $20 + (3 * $300) = $1,120.
        Financing fees = $1,120 - $1,000 = $120.
        """
        option = PaymentOption(
            option_id="OPT_BNPL",
            type=PaymentOptionType.BNPL_INSTALLMENTS,
            down_payment=200.0,
            upfront_fee=20.0,
            installment_amount=300.0,
            num_installments=3,
            frequency_days=30,
        )

        plan = PaymentEngine.evaluate_installments(
            option=option,
            requested_amount=1000.0,
            start_balance=5000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        self.assertTrue(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.INSTALLMENTS)
        self.assertEqual(plan.total_payable_amount, 1120.0)
        self.assertEqual(plan.financing_fees, 120.0)
        self.assertEqual(len(plan.payment_dates), 4)  # Down payment + 3 installments
        self.assertEqual(plan.payment_dates[0], "2026-09-12")
        self.assertEqual(plan.payment_dates[1], "2026-10-12")
        self.assertEqual(plan.payment_dates[2], "2026-11-11")
        self.assertEqual(plan.payment_dates[3], "2026-12-11")

    def test_4_installments_violating_completion_deadline(self):
        """Installments plan completing on Day 90 when completion deadline is Day 45."""
        option = PaymentOption(
            option_id="OPT_SLOW_BNPL",
            type=PaymentOptionType.BNPL_INSTALLMENTS,
            down_payment=100.0,
            installment_amount=300.0,
            num_installments=3,
            frequency_days=30,
        )

        plan = PaymentEngine.evaluate_installments(
            option=option,
            requested_amount=1000.0,
            start_balance=5000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            completion_deadline="2026-10-27",  # 45 days from Sept 12
        )

        self.assertFalse(plan.is_safe)
        self.assertTrue(plan.violates_completion_deadline)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)

    def test_5_partial_payment_valid_and_safe(self):
        """
        Valid partial payment plan meeting all exact challenge rules:
        - Request allows partial payment = True
        - User accepts partial payment = True
        - Safe amount today = $500 (> 0 and < $1,000 requested)
        - Completion deadline = 2026-10-12 (30 days out)
        - Exactly two payments: $500 today, $500 on completion date
        - Amounts sum exactly to $1,000
        - Full payment is possible by completion date
        """
        # User starting balance = $1,500, buffer = $1,000 -> Safe today = $500
        # Salary of $2,000 arrives on 2026-09-20.
        events = [
            FinancialEvent(
                event_id="EVT_SALARY",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-09-20",
                category="SALARY",
            )
        ]

        plan = PaymentEngine.evaluate_partial_payment(
            requested_amount=1000.0,
            start_balance=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            completion_deadline="2026-10-12",
            events=events,
            allows_partial_payment=True,
            user_accepts_partial_payment=True,
        )

        self.assertTrue(plan.is_valid)
        self.assertTrue(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.PARTIAL_PAYMENT)
        self.assertEqual(len(plan.payment_dates), 2)
        self.assertEqual(plan.payment_amounts, [500.0, 500.0])
        self.assertEqual(sum(plan.payment_amounts), 1000.0)

    def test_6_partial_payment_rejected_user_refuses(self):
        """Partial payment rejected if user does NOT accept partial payment."""
        plan = PaymentEngine.evaluate_partial_payment(
            requested_amount=1000.0,
            start_balance=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            allows_partial_payment=True,
            user_accepts_partial_payment=False,  # USER REFUSES!
        )

        self.assertFalse(plan.is_valid)
        self.assertFalse(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)
        self.assertTrue(any("does not accept" in r for r in plan.rejection_reasons))

    def test_7_partial_payment_rejected_safe_amount_zero(self):
        """Partial payment rejected when safe amount today is 0 (balance already at buffer)."""
        plan = PaymentEngine.evaluate_partial_payment(
            requested_amount=1000.0,
            start_balance=1000.0,  # Headroom = 0!
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            allows_partial_payment=True,
            user_accepts_partial_payment=True,
        )

        self.assertFalse(plan.is_valid)
        self.assertFalse(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)

    def test_8_partial_payment_rejected_already_fully_affordable(self):
        """Partial payment rejected if safe amount today >= requested amount (partial payment unnecessary)."""
        plan = PaymentEngine.evaluate_partial_payment(
            requested_amount=500.0,
            start_balance=3000.0,  # Headroom = $2,000 >= $500!
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            allows_partial_payment=True,
            user_accepts_partial_payment=True,
        )

        self.assertFalse(plan.is_valid)
        self.assertFalse(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)

    def test_9_wait_plan_safe_within_deadline(self):
        """
        User has $1,200 balance, $1,000 buffer. Wants to buy $800 item.
        Immediate purchase drops balance to $400 (< $1,000 buffer -> Unsafe today).
        Salary of $2,000 arrives on 2026-09-17.
        Wait plan finds safe execution date = 2026-09-17.
        Deadline = 2026-09-30.
        Wait plan is safe and valid!
        """
        events = [
            FinancialEvent(
                event_id="EVT_SALARY_SEPT",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-09-17",
                category="SALARY",
            )
        ]

        plan = PaymentEngine.evaluate_wait(
            requested_amount=800.0,
            start_balance=1200.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            completion_deadline="2026-09-30",
            events=events,
        )

        self.assertTrue(plan.is_safe)
        self.assertEqual(plan.method, PaymentMethod.WAIT)
        self.assertEqual(plan.completion_date, "2026-09-17")
        self.assertFalse(plan.violates_completion_deadline)

    def test_10_wait_plan_violates_deadline(self):
        """Wait plan finds safe date after completion deadline has passed."""
        events = [
            FinancialEvent(
                event_id="EVT_SALARY_LATE",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-10-15",  # Oct 15
                category="SALARY",
            )
        ]

        plan = PaymentEngine.evaluate_wait(
            requested_amount=800.0,
            start_balance=1200.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            completion_deadline="2026-09-25",  # Sept 25 deadline
            events=events,
        )

        self.assertFalse(plan.is_safe)
        self.assertTrue(plan.violates_completion_deadline)
        self.assertEqual(plan.method, PaymentMethod.NOT_RECOMMENDED)

    def test_11_load_options_from_csv(self):
        """Tests parsing options from request_payment_options.csv DataFrame/file."""
        df = pd.DataFrame([
            {
                "option_id": "OPT_UPFRONT",
                "request_id": "REQ_CSV_1",
                "type": "UPFRONT",
                "down_payment": 500.0,
                "installment_amount": 0.0,
                "num_installments": 1,
                "frequency_days": 30,
                "upfront_fee": 0.0,
                "apr_percent": 0.0,
                "allows_partial_payment": True,
            },
            {
                "option_id": "OPT_BNPL_4X",
                "request_id": "REQ_CSV_1",
                "type": "BNPL_INSTALLMENTS",
                "down_payment": 125.0,
                "installment_amount": 125.0,
                "num_installments": 3,
                "frequency_days": 14,
                "upfront_fee": 10.0,
                "apr_percent": 0.0,
                "allows_partial_payment": False,
            },
        ])

        options = PaymentEngine.load_options_from_csv(df)
        self.assertEqual(len(options), 2)
        self.assertEqual(options[0].type, PaymentOptionType.UPFRONT)
        self.assertTrue(options[0].allows_partial_payment)
        self.assertEqual(options[1].type, PaymentOptionType.BNPL_INSTALLMENTS)
        self.assertEqual(options[1].upfront_fee, 10.0)

    def test_12_evaluate_all_plans_comprehensive(self):
        """Tests evaluate_all_plans returning candidates for full, installments, partial, and wait."""
        profile = UserFinancialProfile(
            user_id="U1",
            accounts=[
                FinancialAccount(account_id="ACC1", name="Checking", type=AccountType.CHECKING, current_balance=1500.0)
            ],
            minimum_safety_buffer=1000.0,
        )

        req = PurchaseRequest(
            request_id="REQ_ALL",
            user_id="U1",
            item_name="E-Bike",
            full_price=1200.0,
            offer_expires_at="2026-10-30",
            allows_partial_payment=True,
            user_accepts_partial_payment=True,
            payment_options=[
                PaymentOption(
                    option_id="OPT_BNPL",
                    type=PaymentOptionType.BNPL_INSTALLMENTS,
                    down_payment=300.0,
                    installment_amount=300.0,
                    num_installments=3,
                    frequency_days=14,
                )
            ],
        )

        plans = PaymentEngine.evaluate_all_plans(
            request=req,
            start_balance=profile,
            as_of_date=self.start_date,
        )

        self.assertTrue(len(plans) >= 4)
        methods = [p.method for p in plans]
        # Should evaluate full, installments, partial, and wait
        self.assertTrue(any(p.option_id == "OPT_FULL" or "FULL" in p.plan_id for p in plans))
        self.assertTrue(any(p.option_id == "OPT_BNPL" for p in plans))
        self.assertTrue(any("PARTIAL" in p.plan_id for p in plans))
        self.assertTrue(any("WAIT" in p.plan_id for p in plans))


if __name__ == "__main__":
    unittest.main()
