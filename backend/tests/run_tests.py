"""
Standard Library Test Runner for Dataset Loader & Normalization Layer
"""

import sys
import unittest
import pandas as pd
from app.data.loader import DataLoader, DataValidationError
from app.models.financial import AccountType, EventType, EventStatus
from app.models.requests import PaymentOptionType


class TestDataLoader(unittest.TestCase):

    def test_load_user_profiles_valid(self):
        loader = DataLoader()
        accounts_df = pd.DataFrame([
            {
                "user_id": "USER_101",
                "account_id": "ACC_001",
                "type": "CHECKING",
                "current_balance": 1500.50,
                "currency": "USD",
                "minimum_safety_buffer": 1000.0,
            },
            {
                "user_id": "USER_101",
                "account_id": "ACC_002",
                "type": "CREDIT_CARD",
                "current_balance": -250.0,
                "credit_limit": 2000.0,
                "minimum_payment_due": 25.0,
            }
        ])

        loader.load_user_profiles_from_df(accounts_df)
        profile = loader.get_user_profile("USER_101")

        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, "USER_101")
        self.assertEqual(len(profile.accounts), 2)
        self.assertEqual(profile.accounts[0].type, AccountType.CHECKING)
        self.assertEqual(profile.accounts[0].current_balance, 1500.50)
        self.assertEqual(profile.accounts[1].type, AccountType.CREDIT_CARD)
        self.assertEqual(profile.accounts[1].minimum_payment_due, 25.0)

    def test_missing_amount_preserved_never_zeroed(self):
        """CRITICAL MANDATE: Missing financial amounts MUST remain None, never 0.0."""
        loader = DataLoader()
        events_df = pd.DataFrame([
            {
                "event_id": "EVT_NULL_AMT",
                "user_id": "USER_101",
                "account_id": "ACC_001",
                "event_type": "EXPENSE",
                "status": "PENDING",
                "amount": None,  # NaN / None
                "currency": "USD",
                "event_date": "2026-09-20",
                "category": "UTILITIES",
            }
        ])

        events = loader.load_financial_events_from_df(events_df)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].amount)
        self.assertNotEqual(events[0].amount, 0.0)

    def test_currency_normalization(self):
        loader = DataLoader()
        events_df = pd.DataFrame([
            {
                "event_id": "EVT_EUR",
                "user_id": "USER_102",
                "account_id": "ACC_001",
                "event_type": "INCOME",
                "status": "CONFIRMED",
                "amount": 100.0,
                "currency": "EUR",  # 1 EUR = 1.08 USD
                "event_date": "2026-09-15",
                "category": "SALARY",
            }
        ])

        events = loader.load_financial_events_from_df(events_df)
        self.assertEqual(events[0].currency, "USD")
        self.assertEqual(events[0].amount, 108.0)  # 100 * 1.08

    def test_lifecycle_deduplication_related_event_id(self):
        """
        If event B has related_event_id referencing event A and status is CONFIRMED,
        event A is marked as EventStatus.SUPERSEDED.
        """
        loader = DataLoader()
        events_df = pd.DataFrame([
            {
                "event_id": "EVT_PENDING_RENT",
                "user_id": "USER_103",
                "account_id": "ACC_001",
                "event_type": "EXPENSE",
                "status": "PENDING",
                "amount": 1200.0,
                "event_date": "2026-09-01",
                "category": "RENT",
            },
            {
                "event_id": "EVT_CONFIRMED_RENT",
                "user_id": "USER_103",
                "account_id": "ACC_001",
                "event_type": "EXPENSE",
                "status": "CONFIRMED",
                "amount": 1200.0,
                "event_date": "2026-09-01",
                "category": "RENT",
                "related_event_id": "EVT_PENDING_RENT",  # Points to original pending event
            }
        ])

        events = loader.load_financial_events_from_df(events_df)
        event_dict = {e.event_id: e for e in events}

        self.assertEqual(event_dict["EVT_PENDING_RENT"].status, EventStatus.SUPERSEDED)
        self.assertEqual(event_dict["EVT_CONFIRMED_RENT"].status, EventStatus.CONFIRMED)

    def test_missing_required_columns_raises_error(self):
        loader = DataLoader()
        malformed_df = pd.DataFrame([
            {"user_id": "USER_104"}  # missing account_id, type, current_balance
        ])

        with self.assertRaises(DataValidationError) as context:
            loader.load_user_profiles_from_df(malformed_df)
        self.assertIn("missing required column(s)", str(context.exception))

    def test_invalid_date_format_raises_error(self):
        loader = DataLoader()
        events_df = pd.DataFrame([
            {
                "event_id": "EVT_BAD_DATE",
                "user_id": "USER_105",
                "account_id": "ACC_001",
                "event_type": "EXPENSE",
                "status": "CONFIRMED",
                "amount": 50.0,
                "event_date": "INVALID_DATE_STRING",
                "category": "GROCERIES",
            }
        ])

        with self.assertRaises(DataValidationError) as context:
            loader.load_financial_events_from_df(events_df)
        self.assertIn("Invalid date format", str(context.exception))

    def test_relational_access_methods(self):
        loader = DataLoader()

        # Load Requests & Options
        req_df = pd.DataFrame([
            {
                "request_id": "REQ_001",
                "user_id": "USER_200",
                "item_name": "Laptop",
                "full_price": 1200.0,
            }
        ])
        opt_df = pd.DataFrame([
            {
                "option_id": "OPT_001",
                "request_id": "REQ_001",
                "type": "BNPL_INSTALLMENTS",
                "down_payment": 300.0,
                "installment_amount": 300.0,
                "num_installments": 3,
                "frequency_days": 30,
            }
        ])

        loader.load_requests_from_df(req_df, opt_df)
        user_reqs = loader.get_requests("USER_200")
        req_opts = loader.get_payment_options("REQ_001")

        self.assertEqual(len(user_reqs), 1)
        self.assertEqual(user_reqs[0].item_name, "Laptop")
        self.assertEqual(len(req_opts), 1)
        self.assertEqual(req_opts[0].type, PaymentOptionType.BNPL_INSTALLMENTS)
        self.assertEqual(req_opts[0].down_payment, 300.0)


from tests.test_ai_evidence import TestAIEvidenceExtraction
from tests.test_financial_state import TestFinancialStateEngine
from tests.test_forecast_engine import TestForecastEngine
from tests.test_amount_safe_engine import TestAmountSafeEngine
from tests.test_payment_engine import TestPaymentEngine
from tests.test_spending_optimizer import TestSpendingOptimizer
from tests.test_decision_engine import TestDecisionEngine
from tests.test_explanation_generator import TestExplanationGenerator
from tests.test_api_routes import TestAPIRoutes


if __name__ == "__main__":
    unittest.main()
