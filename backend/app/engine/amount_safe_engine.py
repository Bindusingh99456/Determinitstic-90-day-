"""
Amount Safe To Pay Engine
Determines the maximum amount that can safely be paid TODAY before optional spending changes,
capped at requested_amount.
"""

from datetime import date
from typing import List, Optional, Union
from app.models.financial import UserFinancialProfile, FinancialState, FinancialEvent
from app.models.requests import PurchaseRequest
from app.models.evidence import ExtractedFact
from app.engine.forecast_engine import ForecastEngine, DEFAULT_EXCHANGE_RATES
from app.utils.date_helpers import parse_date
from app.utils.logger import logger


def convert_currency(amount: Optional[float], from_curr: str, to_curr: str) -> float:
    """Converts monetary amount between currencies using DEFAULT_EXCHANGE_RATES."""
    if amount is None or amount <= 0:
        return 0.0
    from_c = (from_curr or "USD").upper()
    to_c = (to_curr or "USD").upper()
    if from_c == to_c:
        return float(amount)

    from_rate = DEFAULT_EXCHANGE_RATES.get(from_c, 1.0)
    to_rate = DEFAULT_EXCHANGE_RATES.get(to_c, 1.0)
    usd_val = float(amount) * from_rate
    return usd_val / to_rate


class AmountSafeEngine:
    """
    Deterministic solver for calculating maximum safe immediate payment amount today.
    """

    @staticmethod
    def calculate_amount_safe_to_pay(
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        requested_amount: float,
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        currency: str = "USD",
        base_currency: str = "USD",
        horizon_days: int = 90,
    ) -> float:
        """
        Calculates maximum amount safe to pay TODAY before optional spending changes.

        Guarantees:
        - 0.0 <= amount_safe_to_pay <= requested_amount
        - Preserves minimum_balance_to_keep at all times in forecast horizon
        - Accounts for confirmed/recurring income and expenses, payment obligations, and AI evidence
        - Does NOT assume optional spending changes or cutbacks
        - Excludes unrealized investments and pending credits
        - Handles currency conversion accurately
        """
        if requested_amount <= 0:
            return 0.0

        start_date_obj = parse_date(start_date)

        # Extend horizon if completion deadline is further than default horizon_days
        effective_horizon = horizon_days
        if completion_deadline:
            deadline_obj = parse_date(completion_deadline)
            days_to_deadline = (deadline_obj - start_date_obj).days
            if days_to_deadline > effective_horizon:
                effective_horizon = days_to_deadline

        # Initialize Forecast Engine
        forecast_engine = ForecastEngine(
            start_balance=start_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            events=events,
            facts=facts,
            base_currency=base_currency,
        )

        # Baseline cashflow trajectory (no additional outflows, no optional cutbacks)
        curve = forecast_engine.simulate_90day_balance_curve(horizon_days=effective_horizon)

        # Find minimum headroom above safety buffer across all days
        min_headroom_base = min(
            record["balance"] - forecast_engine.minimum_balance_to_keep
            for record in curve
        )

        # Convert requested_amount to base_currency
        req_amount_base = convert_currency(requested_amount, currency, forecast_engine.base_currency)

        # Compute safe payment in base currency
        max_safe_base = max(0.0, min(req_amount_base, min_headroom_base))

        # Convert safe payment back to requested currency
        max_safe_req_curr = convert_currency(max_safe_base, forecast_engine.base_currency, currency)

        # Clamp between 0.0 and requested_amount
        final_safe_amount = max(0.0, min(float(requested_amount), max_safe_req_curr))
        return round(final_safe_amount, 2)

    @classmethod
    def calculate_for_request(
        cls,
        profile: UserFinancialProfile,
        events: List[FinancialEvent],
        request: PurchaseRequest,
        facts: Optional[List[ExtractedFact]] = None,
        as_of_date: str = "2026-09-12",
    ) -> float:
        """Helper to calculate amount_safe_to_pay directly from PurchaseRequest and UserFinancialProfile."""
        return cls.calculate_amount_safe_to_pay(
            start_balance=profile,
            requested_amount=request.full_price,
            minimum_balance_to_keep=profile.minimum_safety_buffer or 1000.0,
            start_date=as_of_date,
            completion_deadline=request.offer_expires_at,
            events=events,
            facts=facts,
            currency=request.currency or "USD",
            base_currency=profile.base_currency or "USD",
        )
