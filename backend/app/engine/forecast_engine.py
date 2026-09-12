"""
Deterministic 90-Day Cashflow Forecast Engine
Simulates day-by-day liquid balances over a 90-day horizon (t = 0 ... 90).
Applies confirmed income, recurring income, confirmed expenses, recurring expenses, and AI evidence.
Calculates minimum projected balance, evaluates payment plan safety, and finds earliest safe execution date.
"""

import calendar
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple, Optional, Union
from app.models.financial import (
    UserFinancialProfile,
    FinancialState,
    FinancialEvent,
    EventType,
    EventStatus,
    AccountType,
)
from app.models.evidence import ExtractedFact
from app.services.evidence_service import EvidenceService
from app.utils.date_helpers import parse_date, adjust_for_weekend
from app.utils.logger import logger


DEFAULT_EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "INR": 0.012,
    "CAD": 0.74,
    "AUD": 0.65,
    "JPY": 0.0067,
}


def convert_to_base_currency(amount: Optional[float], from_curr: str, to_curr: str = "USD") -> float:
    """Converts amount to base currency. Returns 0.0 if amount is None."""
    if amount is None:
        return 0.0
    from_c = (from_curr or "USD").upper()
    to_c = (to_curr or "USD").upper()

    if from_c == to_c:
        return float(amount)

    from_rate = DEFAULT_EXCHANGE_RATES.get(from_c, 1.0)
    to_rate = DEFAULT_EXCHANGE_RATES.get(to_c, 1.0)
    usd_val = float(amount) * from_rate
    return usd_val / to_rate


class ForecastEngine:
    """Core deterministic daily cash projection engine."""

    def __init__(
        self,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        additional_outflows: Optional[Any] = None,
        base_currency: str = "USD",
    ):
        self.evidence_service = EvidenceService()
        self.base_currency = base_currency

        # Flexible initialization based on input type
        if isinstance(start_balance, FinancialState):
            self.start_balance = float(start_balance.available_balance)
            self.minimum_balance_to_keep = float(start_balance.minimum_balance_to_keep)
            self.start_date = parse_date(start_balance.as_of_date)
            self.base_currency = start_balance.base_currency or "USD"
        elif isinstance(start_balance, UserFinancialProfile):
            self.start_balance = float(sum(
                acc.current_balance
                for acc in start_balance.accounts
                if acc.type in [AccountType.CHECKING, AccountType.SAVINGS, AccountType.INVESTMENT_LIQUID]
            ))
            self.minimum_balance_to_keep = float(start_balance.minimum_safety_buffer or 1000.0)
            self.start_date = parse_date(start_date)
            self.base_currency = start_balance.base_currency or "USD"
        else:
            self.start_balance = float(start_balance)
            self.minimum_balance_to_keep = float(minimum_balance_to_keep)
            self.start_date = parse_date(start_date)

        raw_events = events or []
        if facts:
            self.events = self.evidence_service.merge_facts_with_events(raw_events, facts)
        else:
            self.events = raw_events

        self.initial_outflows = self._normalize_outflows(additional_outflows)

    def _normalize_outflows(self, raw_outflows: Any) -> List[Tuple[date, float, str]]:
        """Normalizes various payment schedule formats into List[Tuple[date, float, str]]."""
        normalized: List[Tuple[date, float, str]] = []
        if not raw_outflows:
            return normalized

        if not isinstance(raw_outflows, list):
            raw_outflows = [raw_outflows]

        for item in raw_outflows:
            if isinstance(item, (tuple, list)):
                if len(item) >= 2:
                    d = parse_date(item[0])
                    amt = float(item[1])
                    desc = str(item[2]) if len(item) > 2 else "Custom Payment"
                    normalized.append((d, amt, desc))
            elif isinstance(item, dict):
                d_val = item.get("date") or item.get("payment_date") or item.get("event_date") or self.start_date
                d = parse_date(d_val)
                amt = float(item.get("amount", 0.0))
                desc = str(item.get("description", "Custom Payment"))
                normalized.append((d, amt, desc))
            elif hasattr(item, "amount"):
                d_val = getattr(item, "date", None) or getattr(item, "event_date", None) or getattr(item, "effective_start_date", None) or self.start_date
                d = parse_date(d_val)
                amt = float(getattr(item, "amount", 0.0))
                desc = str(getattr(item, "description", "Custom Payment"))
                normalized.append((d, amt, desc))

        return normalized

    def simulate_90day_balance_curve(
        self,
        additional_outflows: Optional[Any] = None,
        horizon_days: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Calculates daily balance B(t) for t = 0..horizon_days.
        Returns list of daily balance records [{day, date, balance, inflow, outflow, net_change, events}].
        """
        logger.debug(f"Simulating {horizon_days}-day balance curve starting from {self.start_date} with balance ${self.start_balance:.2f}")

        end_date = self.start_date + timedelta(days=horizon_days)
        extra_outflows = self._normalize_outflows(additional_outflows)
        all_custom_outflows = self.initial_outflows + extra_outflows

        # Initialize daily map: date -> {inflow, outflow, descriptions}
        daily_map: Dict[date, Dict[str, Any]] = {
            self.start_date + timedelta(days=i): {"inflow": 0.0, "outflow": 0.0, "events": []}
            for i in range(horizon_days + 1)
        }

        # 1. Map events (income & expenses) across 90-day window
        for evt in self.events:
            if evt.status in [EventStatus.CANCELLED, EventStatus.FAILED, EventStatus.SUPERSEDED]:
                continue

            if evt.amount is None:
                continue

            evt_date = parse_date(evt.event_date)
            amt_usd = convert_to_base_currency(evt.amount, evt.currency, self.base_currency)

            # Income Handling
            if evt.event_type == EventType.INCOME:
                if evt.status == EventStatus.PENDING:
                    # MANDATE: Pending credits are NOT liquid cash
                    continue

                if not evt.is_recurring:
                    if self.start_date <= evt_date <= end_date:
                        # Payday calendar shift adjustment for deposits
                        adjusted_d = adjust_for_weekend(evt_date, shift_type="PRECEDING_FRIDAY")
                        if adjusted_d in daily_map:
                            daily_map[adjusted_d]["inflow"] += amt_usd
                            daily_map[adjusted_d]["events"].append(f"Income: {evt.category} (${amt_usd:.2f})")
                else:
                    rec_dates = self._get_recurring_dates(
                        anchor_date=evt_date,
                        pattern=evt.recurrence_pattern or "MONTHLY",
                        horizon_start=self.start_date,
                        horizon_end=end_date,
                    )
                    for d in rec_dates:
                        adjusted_d = adjust_for_weekend(d, shift_type="PRECEDING_FRIDAY")
                        if adjusted_d in daily_map:
                            daily_map[adjusted_d]["inflow"] += amt_usd
                            daily_map[adjusted_d]["events"].append(f"Rec Income: {evt.category} (${amt_usd:.2f})")

            # Expense Handling
            elif evt.event_type in [EventType.EXPENSE, EventType.INVESTMENT_CALL, EventType.TRANSFER]:
                if not evt.is_recurring:
                    if self.start_date <= evt_date <= end_date:
                        if evt_date in daily_map:
                            daily_map[evt_date]["outflow"] += amt_usd
                            daily_map[evt_date]["events"].append(f"Expense: {evt.category} (${amt_usd:.2f})")
                else:
                    rec_dates = self._get_recurring_dates(
                        anchor_date=evt_date,
                        pattern=evt.recurrence_pattern or "MONTHLY",
                        horizon_start=self.start_date,
                        horizon_end=end_date,
                    )
                    for d in rec_dates:
                        if d in daily_map:
                            daily_map[d]["outflow"] += amt_usd
                            daily_map[d]["events"].append(f"Rec Expense: {evt.category} (${amt_usd:.2f})")

        # 2. Map custom payment outflows
        for p_date, p_amt, p_desc in all_custom_outflows:
            if self.start_date <= p_date <= end_date:
                if p_date in daily_map:
                    daily_map[p_date]["outflow"] += p_amt
                    daily_map[p_date]["events"].append(f"Purchase Outflow: {p_desc} (${p_amt:.2f})")

        # 3. Simulate day-by-day cash trajectory
        daily_curve: List[Dict[str, Any]] = []
        current_balance = self.start_balance

        for i in range(horizon_days + 1):
            cur_date = self.start_date + timedelta(days=i)
            day_data = daily_map[cur_date]

            inflow = day_data["inflow"]
            outflow = day_data["outflow"]
            net_change = inflow - outflow

            current_balance += net_change

            daily_curve.append({
                "day": i,
                "date": cur_date.strftime("%Y-%m-%d"),
                "balance": round(current_balance, 2),
                "inflow": round(inflow, 2),
                "outflow": round(outflow, 2),
                "net_change": round(net_change, 2),
                "events": day_data["events"],
            })

        return daily_curve

    def forecast_balance(self, target_date: Union[str, date], additional_outflows: Optional[Any] = None) -> float:
        """Returns projected liquid balance on a specific target date."""
        t_date = parse_date(target_date)
        if t_date < self.start_date:
            return round(self.start_balance, 2)

        days_ahead = (t_date - self.start_date).days
        curve = self.simulate_90day_balance_curve(additional_outflows=additional_outflows, horizon_days=max(90, days_ahead))

        if days_ahead < len(curve):
            return curve[days_ahead]["balance"]
        return curve[-1]["balance"]

    def minimum_forecast_balance(self, additional_outflows: Optional[Any] = None, horizon_days: int = 90) -> float:
        """Returns the lowest projected balance across the horizon."""
        curve = self.simulate_90day_balance_curve(additional_outflows=additional_outflows, horizon_days=horizon_days)
        return min(record["balance"] for record in curve)

    def is_safe_plan(
        self,
        payment_schedule: Optional[Any] = None,
        full_price: Optional[float] = None,
        additional_outflows: Optional[Any] = None,
        horizon_days: int = 90,
    ) -> bool:
        """
        Determines whether a payment plan / schedule maintains balance >= minimum_balance_to_keep
        and >= 0 at all times across the 90-day forecast horizon.
        """
        outflows_to_test = []
        if payment_schedule:
            outflows_to_test.extend(self._normalize_outflows(payment_schedule))
        if additional_outflows:
            outflows_to_test.extend(self._normalize_outflows(additional_outflows))
        if full_price and not outflows_to_test:
            outflows_to_test.append((self.start_date, float(full_price), "Upfront Purchase"))

        min_bal = self.minimum_forecast_balance(additional_outflows=outflows_to_test, horizon_days=horizon_days)
        is_safe = min_bal >= self.minimum_balance_to_keep and min_bal >= 0.0
        return is_safe

    def first_safe_full_payment_date(self, full_price: float, max_wait_days: int = 90) -> Optional[str]:
        """
        Finds the earliest date (start_date + offset) where paying full_price upfront
        maintains the safety buffer across the 90-day horizon.
        Returns YYYY-MM-DD string or None if impossible within max_wait_days.
        """
        for offset in range(max_wait_days + 1):
            exec_date = self.start_date + timedelta(days=offset)
            schedule = [(exec_date, full_price, "Upfront Full Payment")]

            # Simulate curve from start_date up to exec_date + 90 days
            horizon = offset + 90
            curve = self.simulate_90day_balance_curve(additional_outflows=schedule, horizon_days=horizon)

            min_bal = min(record["balance"] for record in curve)
            if min_bal >= self.minimum_balance_to_keep and min_bal >= 0.0:
                return exec_date.strftime("%Y-%m-%d")

        return None

    def _get_recurring_dates(
        self,
        anchor_date: date,
        pattern: str,
        horizon_start: date,
        horizon_end: date,
    ) -> List[date]:
        """Generates all recurrence dates for a pattern within [horizon_start, horizon_end]."""
        pattern_upper = (pattern or "MONTHLY").upper().strip()
        results: List[date] = []

        if pattern_upper == "WEEKLY":
            d = anchor_date
            if d < horizon_start:
                days_diff = (horizon_start - d).days
                steps = (days_diff + 6) // 7
                d = d + timedelta(days=steps * 7)
            while d <= horizon_end:
                results.append(d)
                d += timedelta(days=7)

        elif pattern_upper in ["BIWEEKLY", "FORTNIGHTLY"]:
            d = anchor_date
            if d < horizon_start:
                days_diff = (horizon_start - d).days
                steps = (days_diff + 13) // 14
                d = d + timedelta(days=steps * 14)
            while d <= horizon_end:
                results.append(d)
                d += timedelta(days=14)

        elif pattern_upper == "MONTHLY":
            target_dom = anchor_date.day
            cur_year = anchor_date.year
            cur_month = anchor_date.month

            # Advance cur_year/cur_month to horizon_start's month/year
            while (cur_year < horizon_start.year) or (cur_year == horizon_start.year and cur_month < horizon_start.month):
                cur_month += 1
                if cur_month > 12:
                    cur_month = 1
                    cur_year += 1

            while True:
                max_d = calendar.monthrange(cur_year, cur_month)[1]
                actual_d = min(target_dom, max_d)
                dt = date(cur_year, cur_month, actual_d)

                if dt > horizon_end:
                    break
                if dt >= horizon_start:
                    results.append(dt)

                cur_month += 1
                if cur_month > 12:
                    cur_month = 1
                    cur_year += 1

        elif pattern_upper in ["ANNUALLY", "YEARLY"]:
            cur_year = anchor_date.year
            target_month = anchor_date.month
            target_day = anchor_date.day

            while cur_year <= horizon_end.year:
                max_d = calendar.monthrange(cur_year, target_month)[1]
                dt = date(cur_year, target_month, min(target_day, max_d))
                if horizon_start <= dt <= horizon_end:
                    results.append(dt)
                cur_year += 1

        else:
            d = anchor_date
            while d < horizon_start:
                d += timedelta(days=30)
            while d <= horizon_end:
                results.append(d)
                d += timedelta(days=30)

        return results
