"""
Unit tests for 90-Day Financial Forecast Engine (ForecastEngine)
Tests immediate purchases, future purchases, delayed salaries, recurring expenses,
minimum safety balance violations, multiple future payments, payment plans, and partial payments.
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
from app.engine.forecast_engine import ForecastEngine


class TestForecastEngine(unittest.TestCase):

    def setUp(self):
        self.start_date = "2026-09-12"

    def test_1_immediate_purchase_safe(self):
        """Immediate purchase where balance remains well above safety buffer."""
        engine = ForecastEngine(
            start_balance=3000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        schedule = [("2026-09-12", 500.0, "Laptop Downpayment")]
        is_safe = engine.is_safe_plan(payment_schedule=schedule)
        min_bal = engine.minimum_forecast_balance(additional_outflows=schedule)

        self.assertTrue(is_safe)
        self.assertEqual(min_bal, 2500.0)

    def test_2_future_purchase_timeline(self):
        """Purchase scheduled 30 days in the future is reflected on the exact date."""
        engine = ForecastEngine(
            start_balance=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        schedule = [("2026-10-12", 500.0, "Future Tech Gadget")]

        # Before purchase date (Sept 20)
        bal_before = engine.forecast_balance("2026-09-20", additional_outflows=schedule)
        self.assertEqual(bal_before, 2000.0)

        # After purchase date (Oct 15)
        bal_after = engine.forecast_balance("2026-10-15", additional_outflows=schedule)
        self.assertEqual(bal_after, 1500.0)

    def test_3_salary_arriving_later_determines_first_safe_date(self):
        """
        User has $1,200 balance and $1,000 buffer. Wants to buy $500 item.
        Immediate purchase drops balance to $700 (< $1,000 buffer -> UNSAFE).
        Salary of $2,000 arrives on 2026-09-17.
        First safe payment date MUST be 2026-09-17.
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

        engine = ForecastEngine(
            start_balance=1200.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
        )

        # Paying today is unsafe
        is_safe_today = engine.is_safe_plan(full_price=500.0)
        self.assertFalse(is_safe_today)

        # Find earliest safe execution date
        safe_date = engine.first_safe_full_payment_date(full_price=500.0)
        self.assertEqual(safe_date, "2026-09-17")

    def test_4_recurring_expenses_simulation(self):
        """Monthly recurring rent expense of $1,200 deducted every month across 90 days."""
        events = [
            FinancialEvent(
                event_id="EVT_RENT_REC",
                user_id="U1",
                account_id="ACC_CHK",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1200.0,
                event_date="2026-09-15",
                is_recurring=True,
                recurrence_pattern="MONTHLY",
                category="RENT",
            )
        ]

        engine = ForecastEngine(
            start_balance=5000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
            events=events,
        )

        curve = engine.simulate_90day_balance_curve(horizon_days=90)

        # Sept 12..14 balance = 5000
        # Sept 15 balance = 3800
        # Oct 15 balance = 2600
        # Nov 15 balance = 1400
        bal_oct_20 = engine.forecast_balance("2026-10-20")
        self.assertEqual(bal_oct_20, 2600.0)

        bal_nov_20 = engine.forecast_balance("2026-11-20")
        self.assertEqual(bal_nov_20, 1400.0)

    def test_5_minimum_balance_violations(self):
        """Purchase violating safety buffer threshold returns False."""
        engine = ForecastEngine(
            start_balance=1500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        # $800 purchase drops balance to $700 (< $1,000 buffer)
        is_safe = engine.is_safe_plan(full_price=800.0)
        self.assertFalse(is_safe)

    def test_6_multiple_future_payments(self):
        """3 staged payments of $300 on Day 0, Day 30, and Day 60."""
        engine = ForecastEngine(
            start_balance=2500.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        schedule = [
            ("2026-09-12", 300.0, "Tranche 1"),
            ("2026-10-12", 300.0, "Tranche 2"),
            ("2026-11-12", 300.0, "Tranche 3"),
        ]

        is_safe = engine.is_safe_plan(payment_schedule=schedule)
        min_bal = engine.minimum_forecast_balance(additional_outflows=schedule)

        self.assertTrue(is_safe)
        self.assertEqual(min_bal, 1600.0)  # 2500 - 900 = 1600

    def test_7_payment_plans_installments(self):
        """BNPL plan with $200 downpayment + 3 biweekly installments of $200."""
        engine = ForecastEngine(
            start_balance=2000.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        schedule = [
            ("2026-09-12", 200.0, "Downpayment"),
            ("2026-09-26", 200.0, "Installment 1"),
            ("2026-10-10", 200.0, "Installment 2"),
            ("2026-10-24", 200.0, "Installment 3"),
        ]

        is_safe = engine.is_safe_plan(payment_schedule=schedule)
        min_bal = engine.minimum_forecast_balance(additional_outflows=schedule)

        self.assertTrue(is_safe)
        self.assertEqual(min_bal, 1200.0)  # 2000 - 800 = 1200

    def test_8_partial_payment_and_deposit(self):
        """Partial deposit today ($400) and remaining balance ($600) upon delivery in 20 days."""
        engine = ForecastEngine(
            start_balance=2200.0,
            minimum_balance_to_keep=1000.0,
            start_date=self.start_date,
        )

        schedule = [
            ("2026-09-12", 400.0, "Partial Deposit"),
            ("2026-10-02", 600.0, "Final Delivery Payment"),
        ]

        is_safe = engine.is_safe_plan(payment_schedule=schedule)
        min_bal = engine.minimum_forecast_balance(additional_outflows=schedule)

        self.assertTrue(is_safe)
        self.assertEqual(min_bal, 1200.0)


if __name__ == "__main__":
    unittest.main()
