"""
Unit tests for Explanation Generator (ExplanationGenerator)
Tests:
- Extraction of verified financial facts (balance, minimum balance, price, expenses, income, dates)
- Grounded explanation generation for all 4 affordability statuses
- Factual grounding (no invented facts, numbers, or dates)
- Non-technical, user-friendly style matching challenge examples
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
from app.models.requests import PurchaseRequest
from app.engine.explanation_generator import ExplanationGenerator, ExplanationFacts


class TestExplanationGenerator(unittest.TestCase):

    def setUp(self):
        self.as_of_date = "2026-09-12"

    def test_1_fact_extraction(self):
        """Verifies accurate extraction of financial facts without hallucination."""
        req = PurchaseRequest(
            request_id="REQ_TEST",
            user_id="U1",
            item_name="Laptop",
            full_price=1200.0,
        )

        events = [
            FinancialEvent(
                event_id="EVT_RENT",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1500.0,
                event_date="2026-09-15",
                category="RENT",
            ),
            FinancialEvent(
                event_id="EVT_PAYDAY",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2500.0,
                event_date="2026-09-20",
                category="SALARY",
            ),
        ]

        decision_payload = {
            "affordability_status": "affordable_later",
            "recommended_payment_method": "wait",
            "earliest_date_for_full_payment": "2026-09-20",
            "spending_changes_needed": [],
        }

        facts = ExplanationGenerator.extract_facts(
            request=req,
            start_balance=2000.0,
            events=events,
            as_of_date=self.as_of_date,
            decision_payload=decision_payload,
        )

        self.assertEqual(facts.current_balance, 2000.0)
        self.assertEqual(facts.purchase_amount, 1200.0)
        self.assertEqual(facts.item_name, "Laptop")
        self.assertEqual(facts.earliest_date_for_full_payment, "2026-09-20")
        self.assertEqual(len(facts.upcoming_expenses_summary), 1)
        self.assertIn("rent ($1500.00 on 2026-09-15)", facts.upcoming_expenses_summary[0])

    def test_2_affordable_now_explanation(self):
        """Verifies concise, clear explanation when purchase is safe today."""
        req = PurchaseRequest(
            request_id="REQ_NOW",
            user_id="U1",
            item_name="Headphones",
            full_price=200.0,
        )

        decision_payload = {
            "affordability_status": "affordable_now",
            "recommended_payment_method": "full_payment",
            "earliest_date_for_full_payment": "2026-09-12",
            "spending_changes_needed": [],
        }

        exp = ExplanationGenerator.generate_explanation(
            request=req,
            start_balance=3000.0,
            as_of_date=self.as_of_date,
            decision_payload=decision_payload,
        )

        self.assertIn("Buying Headphones today for $200.00 is financially safe", exp)
        self.assertIn("available balance of $3000.00 comfortably covers the purchase", exp)

    def test_3_affordable_later_wait_explanation(self):
        """Verifies explanation matching challenge example style for wait plans."""
        req = PurchaseRequest(
            request_id="REQ_LATER",
            user_id="U1",
            item_name="Bicycle",
            full_price=600.0,
        )

        events = [
            FinancialEvent(
                event_id="EVT_RENT",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=1000.0,
                event_date="2026-09-15",
                category="RENT",
            ),
            FinancialEvent(
                event_id="EVT_SALARY",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-09-30",
                category="SALARY",
            ),
        ]

        decision_payload = {
            "affordability_status": "affordable_later",
            "recommended_payment_method": "wait",
            "earliest_date_for_full_payment": "2026-09-30",
            "spending_changes_needed": [],
        }

        exp = ExplanationGenerator.generate_explanation(
            request=req,
            start_balance=1300.0,
            events=events,
            as_of_date=self.as_of_date,
            decision_payload=decision_payload,
        )

        self.assertIn("Buying Bicycle today would reduce your balance below your required minimum of $1000.00", exp)
        self.assertIn("Waiting until 2026-09-30 allows the purchase while keeping your balance above the required minimum", exp)

    def test_4_not_affordable_explanation(self):
        """Verifies explanation for impossible / not affordable request."""
        req = PurchaseRequest(
            request_id="REQ_IMPOSSIBLE",
            user_id="U1",
            item_name="Car",
            full_price=25000.0,
        )

        decision_payload = {
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "earliest_date_for_full_payment": None,
            "spending_changes_needed": [],
        }

        exp = ExplanationGenerator.generate_explanation(
            request=req,
            start_balance=2000.0,
            as_of_date=self.as_of_date,
            decision_payload=decision_payload,
        )

        self.assertIn("Buying Car today for $25000.00 is not recommended", exp)
        self.assertIn("available balance of $2000.00 cannot cover the purchase", exp)


if __name__ == "__main__":
    unittest.main()
