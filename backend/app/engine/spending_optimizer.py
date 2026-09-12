"""
Spending Cutback & Optimization Engine
Identifies optional/flexible recurring expense reductions or cancellations,
re-simulates 90-day cashflow forecasts, and determines the minimal set of useful spending changes
(up to 3) required to make a purchase safe or minimize wait days.
"""

from datetime import date, timedelta
from enum import Enum
from typing import List, Dict, Any, Tuple, Optional, Set, Union
from pydantic import BaseModel, Field

from app.models.financial import (
    UserFinancialProfile,
    FinancialState,
    FinancialEvent,
    EventType,
    EventStatus,
)
from app.models.requests import PurchaseRequest, SpendingCutback
from app.models.evidence import ExtractedFact
from app.engine.forecast_engine import ForecastEngine, convert_to_base_currency
from app.utils.date_helpers import parse_date
from app.utils.logger import logger


# Categories that are strictly ESSENTIAL and MUST NEVER be modified
ESSENTIAL_CATEGORY_KEYWORDS = [
    "RENT",
    "MORTGAGE",
    "HOUSING",
    "UTILITIES",
    "ELECTRICITY",
    "WATER",
    "GAS",
    "TRASH",
    "INTERNET",
    "GROCERIES",
    "FOOD_ESSENTIAL",
    "HEALTHCARE",
    "MEDICAL",
    "HEALTH_INSURANCE",
    "PHARMACY",
    "PRESCRIPTIONS",
    "DEBT",
    "LOAN",
    "MORTGAGE_PAYMENT",
    "CAR_PAYMENT",
    "AUTO_LOAN",
    "STUDENT_LOAN",
    "CREDIT_CARD",
    "INSURANCE",
    "AUTO_INSURANCE",
    "HOME_INSURANCE",
    "LIFE_INSURANCE",
    "TAX",
    "TAXES",
    "PROPERTY_TAX",
    "IRS",
    "TUITION",
    "SCHOOL",
    "CHILDCARE",
    "DAYCARE",
    "LEGAL",
    "ALIMONY",
    "CHILD_SUPPORT",
    "MANDATORY",
]


class ActionType(str, Enum):
    STOP = "stop"
    REDUCE_TO = "reduce_to"


class SpendingChange(BaseModel):
    action_str: str  # "stop:<event_id>" or "reduce_to:<event_id>:<new_amount>"
    action_type: ActionType
    event_id: str
    category: str
    original_amount: float
    new_amount: float
    monthly_savings: float
    is_useful: bool = True
    earliest_safe_date: Optional[str] = None
    wait_days: int = 0
    makes_purchase_safe_today: bool = False


class SpendingOptimizationResult(BaseModel):
    recommended_changes: List[SpendingChange] = Field(default_factory=list, description="At most 3 spending changes")
    action_strings: List[str] = Field(default_factory=list, description="List of action strings e.g. ['stop:EVT_1']")
    total_monthly_savings: float = 0.0
    baseline_earliest_safe_date: Optional[str] = None
    baseline_wait_days: int = 999
    baseline_safe_today: bool = False
    optimized_earliest_safe_date: Optional[str] = None
    optimized_wait_days: int = 999
    optimized_safe_today: bool = False


class SpendingOptimizer:
    """Processes lifestyle cutbacks and spending optimizations to restore safety buffer compliance."""

    @staticmethod
    def is_flexible_recurring_expense(
        evt: FinancialEvent, as_of_date: Union[str, date] = "2026-09-12"
    ) -> bool:
        """
        Checks if an event is a candidate for optional spending optimization:
        - Must be EXPENSE type
        - Must be recurring (is_recurring == True)
        - Must be CONFIRMED or active
        - Must NOT be historical non-recurring past transaction
        - Must NOT belong to an essential category or debt obligation
        """
        if evt.event_type != EventType.EXPENSE:
            return False

        if not evt.is_recurring:
            return False

        if evt.status in [EventStatus.CANCELLED, EventStatus.FAILED, EventStatus.SUPERSEDED]:
            return False

        if evt.amount is None or evt.amount <= 0:
            return False

        cat_upper = (evt.category or "").upper().strip()
        for kw in ESSENTIAL_CATEGORY_KEYWORDS:
            if kw in cat_upper:
                return False

        return True

    @classmethod
    def generate_candidate_actions(
        cls, events: List[FinancialEvent], as_of_date: Union[str, date] = "2026-09-12"
    ) -> List[SpendingChange]:
        """Generates all single candidate spending changes (stop and reduce_to) for flexible recurring expenses."""
        candidates: List[SpendingChange] = []

        for evt in events:
            if not cls.is_flexible_recurring_expense(evt, as_of_date):
                continue

            orig_amt = round(evt.amount, 2)
            evt_id = evt.event_id
            cat = evt.category

            # Action 1: STOP (cancel recurring expense)
            candidates.append(
                SpendingChange(
                    action_str=f"stop:{evt_id}",
                    action_type=ActionType.STOP,
                    event_id=evt_id,
                    category=cat,
                    original_amount=orig_amt,
                    new_amount=0.0,
                    monthly_savings=orig_amt,
                )
            )

            # Action 2: REDUCE_TO (reduce by 50%)
            reduced_amt = round(orig_amt / 2.0, 2)
            if reduced_amt > 0 and reduced_amt < orig_amt:
                candidates.append(
                    SpendingChange(
                        action_str=f"reduce_to:{evt_id}:{reduced_amt:.2f}",
                        action_type=ActionType.REDUCE_TO,
                        event_id=evt_id,
                        category=cat,
                        original_amount=orig_amt,
                        new_amount=reduced_amt,
                        monthly_savings=round(orig_amt - reduced_amt, 2),
                    )
                )

        return candidates

    @classmethod
    def apply_changes_to_events(
        cls, events: List[FinancialEvent], changes: List[SpendingChange]
    ) -> List[FinancialEvent]:
        """Creates a deep copy of events list with specified spending changes applied."""
        change_map: Dict[str, SpendingChange] = {c.event_id: c for c in changes}
        modified_events: List[FinancialEvent] = []

        for evt in events:
            if evt.event_id in change_map:
                chg = change_map[evt.event_id]
                if chg.action_type == ActionType.STOP or chg.new_amount == 0.0:
                    mod_evt = evt.model_copy(update={"status": EventStatus.CANCELLED, "amount": 0.0})
                else:
                    mod_evt = evt.model_copy(update={"amount": chg.new_amount})
                modified_events.append(mod_evt)
            else:
                modified_events.append(evt)

        return modified_events

    @classmethod
    def optimize_spending_changes(
        cls,
        requested_amount: float,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        events: List[FinancialEvent],
        facts: Optional[List[ExtractedFact]] = None,
        as_of_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        max_changes: int = 3,
    ) -> SpendingOptimizationResult:
        """
        Determines the optimal set of spending changes (at most 3) to achieve safety or minimize wait days.
        Deterministic ranking rules:
        1. Achieves immediate safety today (wait_days == 0).
        2. Minimizes wait days to safe execution date.
        3. Minimizes total monthly cutback amount (least disruption).
        4. Minimizes number of actions.
        """
        as_of_d = parse_date(as_of_date)

        # 1. Baseline forecast without any changes
        base_forecast = ForecastEngine(
            start_balance=start_balance,
            start_date=as_of_d,
            events=events,
            facts=facts,
        )

        base_safe_today = base_forecast.is_safe_plan(full_price=requested_amount)
        base_safe_date_str = base_forecast.first_safe_full_payment_date(full_price=requested_amount)
        if base_safe_date_str:
            base_safe_date = parse_date(base_safe_date_str)
            base_wait_days = (base_safe_date - as_of_d).days
        else:
            base_safe_date = None
            base_wait_days = 999

        # If baseline is already 100% safe today, no spending cutbacks needed!
        if base_safe_today:
            return SpendingOptimizationResult(
                recommended_changes=[],
                action_strings=[],
                total_monthly_savings=0.0,
                baseline_earliest_safe_date=base_safe_date_str or as_of_d.strftime("%Y-%m-%d"),
                baseline_wait_days=0,
                baseline_safe_today=True,
                optimized_earliest_safe_date=base_safe_date_str or as_of_d.strftime("%Y-%m-%d"),
                optimized_wait_days=0,
                optimized_safe_today=True,
            )

        # 2. Candidate single actions
        candidate_actions = cls.generate_candidate_actions(events, as_of_d)
        if not candidate_actions:
            return SpendingOptimizationResult(
                recommended_changes=[],
                action_strings=[],
                total_monthly_savings=0.0,
                baseline_earliest_safe_date=base_safe_date_str,
                baseline_wait_days=base_wait_days,
                baseline_safe_today=False,
                optimized_earliest_safe_date=base_safe_date_str,
                optimized_wait_days=base_wait_days,
                optimized_safe_today=False,
            )

        # 3. Generate candidate combinations of up to max_changes (1, 2, or 3)
        # Ensuring stop and reduce_to are mutually exclusive per event_id!
        action_sets: List[List[SpendingChange]] = []

        # Single actions
        for act in candidate_actions:
            action_sets.append([act])

        # Pairs
        if max_changes >= 2:
            n = len(candidate_actions)
            for i in range(n):
                for j in range(i + 1, n):
                    act_i, act_j = candidate_actions[i], candidate_actions[j]
                    if act_i.event_id != act_j.event_id:  # Mutually exclusive per event_id
                        action_sets.append([act_i, act_j])

        # Triplets
        if max_changes >= 3:
            n = len(candidate_actions)
            for i in range(n):
                for j in range(i + 1, n):
                    for k in range(j + 1, n):
                        act_i, act_j, act_k = candidate_actions[i], candidate_actions[j], candidate_actions[k]
                        if (
                            act_i.event_id != act_j.event_id
                            and act_i.event_id != act_k.event_id
                            and act_j.event_id != act_k.event_id
                        ):
                            action_sets.append([act_i, act_j, act_k])

        # 4. Evaluate each combination
        evaluated_options = []

        for combo in action_sets:
            mod_events = cls.apply_changes_to_events(events, combo)
            opt_forecast = ForecastEngine(
                start_balance=start_balance,
                start_date=as_of_d,
                events=mod_events,
                facts=facts,
            )

            is_safe_today = opt_forecast.is_safe_plan(full_price=requested_amount)
            safe_date_str = opt_forecast.first_safe_full_payment_date(full_price=requested_amount)
            if safe_date_str:
                s_date = parse_date(safe_date_str)
                w_days = (s_date - as_of_d).days
            else:
                s_date = None
                w_days = 999

            # Determine usefulness
            # A set of changes is useful if:
            # - It makes purchase safe today (w_days == 0), OR
            # - It strictly reduces wait days (w_days < base_wait_days), OR
            # - It satisfies completion deadline when baseline didn't.
            is_useful = False
            if is_safe_today:
                is_useful = True
            elif w_days < base_wait_days:
                is_useful = True
            elif completion_deadline:
                deadline_d = parse_date(completion_deadline)
                if s_date and s_date <= deadline_d and (not base_safe_date or base_safe_date > deadline_d):
                    is_useful = True

            if not is_useful:
                continue

            tot_savings = round(sum(c.monthly_savings for c in combo), 2)

            evaluated_options.append({
                "combo": combo,
                "is_safe_today": is_safe_today,
                "wait_days": w_days,
                "safe_date_str": safe_date_str,
                "total_savings": tot_savings,
                "num_actions": len(combo),
            })

        if not evaluated_options:
            return SpendingOptimizationResult(
                recommended_changes=[],
                action_strings=[],
                total_monthly_savings=0.0,
                baseline_earliest_safe_date=base_safe_date_str,
                baseline_wait_days=base_wait_days,
                baseline_safe_today=False,
                optimized_earliest_safe_date=base_safe_date_str,
                optimized_wait_days=base_wait_days,
                optimized_safe_today=False,
            )

        # 5. Deterministic Ranking
        # Priority 1: Safe today (is_safe_today desc)
        # Priority 2: Smallest wait_days asc
        # Priority 3: Smallest total_savings asc (least disruption)
        # Priority 4: Smallest num_actions asc
        evaluated_options.sort(
            key=lambda x: (
                0 if x["is_safe_today"] else 1,
                x["wait_days"],
                x["total_savings"],
                x["num_actions"],
            )
        )

        best = evaluated_options[0]
        best_combo = best["combo"]

        # Annotate changes in best combo with results
        final_changes = []
        for c in best_combo:
            c_copy = c.model_copy(
                update={
                    "is_useful": True,
                    "earliest_safe_date": best["safe_date_str"],
                    "wait_days": best["wait_days"],
                    "makes_purchase_safe_today": best["is_safe_today"],
                }
            )
            final_changes.append(c_copy)

        return SpendingOptimizationResult(
            recommended_changes=final_changes,
            action_strings=[c.action_str for c in final_changes],
            total_monthly_savings=best["total_savings"],
            baseline_earliest_safe_date=base_safe_date_str,
            baseline_wait_days=base_wait_days,
            baseline_safe_today=base_safe_today,
            optimized_earliest_safe_date=best["safe_date_str"],
            optimized_wait_days=best["wait_days"],
            optimized_safe_today=best["is_safe_today"],
        )

    @staticmethod
    def calculate_cutback_inflows(
        cutbacks: List[SpendingCutback], start_date: date, horizon_days: int = 90
    ) -> List[Tuple[date, float, str]]:
        """
        Generates virtual cash savings tuples for spending cutbacks.
        Preserves backward compatibility interface.
        """
        savings_events: List[Tuple[date, float, str]] = []
        for cb in cutbacks:
            cb_date = parse_date(cb.effective_start_date)
            if cb_date <= start_date + timedelta(days=horizon_days):
                savings_events.append(
                    (cb_date, cb.monthly_savings, f"Cutback Savings: {cb.description}")
                )
        return savings_events
