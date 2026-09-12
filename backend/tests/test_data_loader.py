"""
Unit tests for DataLoader, DataValidationError, missing value preservation,
currency normalization, and lifecycle deduplication.
"""

import pytest
import pandas as pd
from app.data.loader import DataLoader, DataValidationError
from app.models.financial import AccountType, EventType, EventStatus
from app.models.requests import PaymentOptionType


def test_load_user_profiles_valid():
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

    assert profile is not None
    assert profile.user_id == "USER_101"
    assert len(profile.accounts) == 2
    assert profile.accounts[0].type == AccountType.CHECKING
    assert profile.accounts[0].current_balance == 1500.50
    assert profile.accounts[1].type == AccountType.CREDIT_CARD
    assert profile.accounts[1].minimum_payment_due == 25.0


def test_missing_amount_preserved_never_zeroed():
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
    assert len(events) == 1
    assert events[0].amount is None
    assert events[0].amount != 0.0


def test_currency_normalization():
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
    assert events[0].currency == "USD"
    assert events[0].amount == 108.0  # 100 * 1.08


def test_lifecycle_deduplication_related_event_id():
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

    assert event_dict["EVT_PENDING_RENT"].status == EventStatus.SUPERSEDED
    assert event_dict["EVT_CONFIRMED_RENT"].status == EventStatus.CONFIRMED


def test_missing_required_columns_raises_error():
    loader = DataLoader()
    malformed_df = pd.DataFrame([
        {"user_id": "USER_104"}  # missing account_id, type, current_balance
    ])

    with pytest.raises(DataValidationError) as excinfo:
        loader.load_user_profiles_from_df(malformed_df)
    assert "missing required column(s)" in str(excinfo.value)


def test_invalid_date_format_raises_error():
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

    with pytest.raises(DataValidationError) as excinfo:
        loader.load_financial_events_from_df(events_df)
    assert "Invalid date format" in str(excinfo.value)


def test_relational_access_methods():
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

    assert len(user_reqs) == 1
    assert user_reqs[0].item_name == "Laptop"
    assert len(req_opts) == 1
    assert req_opts[0].type == PaymentOptionType.BNPL_INSTALLMENTS
    assert req_opts[0].down_payment == 300.0
