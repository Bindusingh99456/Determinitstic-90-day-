"""
Deterministic Main Decision Engine
Orchestrates AmountSafeEngine, ForecastEngine, PaymentEngine, and SpendingOptimizer
to produce fully reproducible, validated purchase decisions.
"""

from datetime import date, datetime
from typing import List, Dict, Any, Optional, Union, Tuple
from pydantic import BaseModel

from app.models.financial import UserFinancialProfile, FinancialState, FinancialEvent
from app.models.requests import PurchaseRequest, PaymentOption, PaymentPlan, PaymentMethod
from app.models.evidence import ExtractedFact
from app.models.decision import AffordabilityStatus, FinalDecisionOutput
from app.engine.forecast_engine import ForecastEngine
from app.engine.amount_safe_engine import AmountSafeEngine
from app.engine.payment_engine import PaymentEngine
from app.engine.spending_optimizer import SpendingOptimizer, SpendingOptimizationResult
from app.engine.explanation_generator import ExplanationGenerator
from app.utils.date_helpers import parse_date
from app.utils.logger import logger


class DecisionEngine:
    """Complete deterministic purchase decision orchestrator."""

    @classmethod
    def evaluate_request(
        cls,
        request: PurchaseRequest,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        as_of_date: Union[str, date] = "2026-09-12",
        options_override: Optional[List[PaymentOption]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates purchase request and returns exact required dictionary schema:
        {
            "request_id": "...",
            "amount_safe_to_pay": 0.0,
            "affordability_status": "...",
            "recommended_payment_method": "...",
            "payment_plan": {...},
            "earliest_date_for_full_payment": "...",
            "spending_changes_needed": [...],
            "decision_explanation": "..."
        }
        """
        as_of_d = parse_date(as_of_date)
        req_id = request.request_id
        full_price = request.full_price
        completion_deadline = request.offer_expires_at

        logger.info(f"Evaluating purchase request {req_id} (Price: ${full_price:.2f}) as of {as_of_d}")

        # 1. Determine maximum safe amount today
        safe_amt_today = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=start_balance,
            requested_amount=full_price,
            start_date=as_of_d,
            completion_deadline=completion_deadline,
            events=events,
            facts=facts,
        )

        # 2. Determine earliest date for full payment (financial capacity independent of preferences)
        base_forecast = ForecastEngine(
            start_balance=start_balance,
            start_date=as_of_d,
            events=events,
            facts=facts,
        )
        earliest_full_date_str = base_forecast.first_safe_full_payment_date(full_price=full_price)

        # 3. Evaluate baseline candidate payment plans (without spending changes)
        baseline_plans = PaymentEngine.evaluate_all_plans(
            request=request,
            start_balance=start_balance,
            events=events,
            facts=facts,
            as_of_date=as_of_d,
            options_override=options_override,
        )

        # Collect all valid safe baseline candidates
        candidate_packages: List[Dict[str, Any]] = []

        for p in baseline_plans:
            if p.is_safe and p.is_valid and p.method != PaymentMethod.NOT_RECOMMENDED:
                candidate_packages.append({
                    "plan": p,
                    "spending_changes": [],
                    "total_payable": p.total_payable_amount,
                    "first_payment_date": parse_date(p.payment_dates[0]) if p.payment_dates else as_of_d,
                    "num_payments": len(p.payment_dates),
                    "option_id": p.option_id or "OPT_DEFAULT",
                    "violates_deadline": p.violates_completion_deadline,
                    "requires_spending_changes": False,
                })

        # 4. Evaluate optional spending changes if baseline plans are insufficient
        opt_res: Optional[SpendingOptimizationResult] = None
        has_safe_baseline_now = any(
            c["plan"].method == PaymentMethod.FULL_PAYMENT and c["first_payment_date"] == as_of_d
            for c in candidate_packages
        )

        if not has_safe_baseline_now:
            opt_res = SpendingOptimizer.optimize_spending_changes(
                requested_amount=full_price,
                start_balance=start_balance,
                events=events or [],
                facts=facts,
                as_of_date=as_of_d,
                completion_deadline=completion_deadline,
            )

            if opt_res and opt_res.recommended_changes:
                # Re-evaluate payment plans under modified event stream with spending changes
                mod_events = SpendingOptimizer.apply_changes_to_events(events or [], opt_res.recommended_changes)
                opt_plans = PaymentEngine.evaluate_all_plans(
                    request=request,
                    start_balance=start_balance,
                    events=mod_events,
                    facts=facts,
                    as_of_date=as_of_d,
                    options_override=options_override,
                )

                for p in opt_plans:
                    if p.is_safe and p.is_valid and p.method != PaymentMethod.NOT_RECOMMENDED:
                        candidate_packages.append({
                            "plan": p,
                            "spending_changes": opt_res.action_strings,
                            "total_payable": p.total_payable_amount,
                            "first_payment_date": parse_date(p.payment_dates[0]) if p.payment_dates else as_of_d,
                            "num_payments": len(p.payment_dates),
                            "option_id": p.option_id or "OPT_DEFAULT",
                            "violates_deadline": p.violates_completion_deadline,
                            "requires_spending_changes": True,
                        })

        # 5. Apply Exact Ranking Rules
        # Rule 1: Complete by desired completion date (violates_deadline == False)
        # Rule 2: No spending changes (requires_spending_changes == False)
        # Rule 3: Minimize total amount paid (total_payable asc)
        # Rule 4: Start payment earlier (first_payment_date asc)
        # Rule 5: Fewer payments (num_payments asc)
        # Rule 6: Lowest payment_option_id (option_id asc)
        if candidate_packages:
            candidate_packages.sort(
                key=lambda x: (
                    1 if x["violates_deadline"] else 0,
                    1 if x["requires_spending_changes"] else 0,
                    x["total_payable"],
                    x["first_payment_date"],
                    x["num_payments"],
                    str(x["option_id"]),
                )
            )
            best_package = candidate_packages[0]
            chosen_plan: PaymentPlan = best_package["plan"]
            chosen_changes: List[str] = best_package["spending_changes"]
        else:
            chosen_plan = PaymentPlan(
                plan_id="PLAN_REJECT",
                method=PaymentMethod.NOT_RECOMMENDED,
                option_id="OPT_NONE",
                description="No safe payment plan available.",
                total_payable_amount=full_price,
                financing_fees=0.0,
                payment_dates=[],
                payment_amounts=[],
                schedule=[],
                is_safe=False,
                is_valid=False,
                rejection_reasons=["Purchase breaches minimum safety buffer and cashflow constraints."],
                minimum_projected_balance=0.0,
                completion_date=as_of_d.strftime("%Y-%m-%d"),
                violates_completion_deadline=True,
            )
            chosen_changes = []

        # 6. Determine Affordability Status and Recommended Method
        rec_method = chosen_plan.method.value if isinstance(chosen_plan.method, PaymentMethod) else str(chosen_plan.method)

        if rec_method == "full_payment" and parse_date(chosen_plan.payment_dates[0]) == as_of_d and not chosen_changes:
            affordability_status = "affordable_now"
        elif rec_method in ["partial_payment", "installments"] and not chosen_changes:
            affordability_status = "affordable_with_plan"
        elif rec_method in ["full_payment", "partial_payment", "installments", "wait"] and (chosen_changes or parse_date(chosen_plan.payment_dates[0]) > as_of_d):
            affordability_status = "affordable_later"
        else:
            affordability_status = "not_affordable"
            rec_method = "not_recommended"

        # 7. Formulate Clear Decision Explanation
        preliminary_payload = {
            "affordability_status": affordability_status,
            "recommended_payment_method": rec_method,
            "earliest_date_for_full_payment": earliest_full_date_str,
            "spending_changes_needed": chosen_changes,
        }

        explanation_str = ExplanationGenerator.generate_explanation(
            request=request,
            start_balance=start_balance,
            events=events,
            as_of_date=as_of_d,
            decision_payload=preliminary_payload,
        )

        # 8. Internal Validation before returning
        result_dict = {
            "request_id": req_id,
            "amount_safe_to_pay": round(float(safe_amt_today), 2),
            "affordability_status": affordability_status,
            "recommended_payment_method": rec_method,
            "payment_plan": chosen_plan.model_dump() if hasattr(chosen_plan, "model_dump") else chosen_plan.__dict__,
            "earliest_date_for_full_payment": earliest_full_date_str,
            "spending_changes_needed": chosen_changes,
            "decision_explanation": explanation_str,
        }

        cls.validate_decision_payload(result_dict, full_price)

        return result_dict

    @classmethod
    def validate_decision_payload(cls, payload: Dict[str, Any], full_price: float) -> None:
        """Strict internal validation check of decision payload."""
        req_id = payload.get("request_id")
        if not req_id:
            raise ValueError("Validation failed: request_id missing.")

        safe_amt = payload.get("amount_safe_to_pay")
        if safe_amt is None or safe_amt < 0.0 or safe_amt > full_price + 1e-4:
            raise ValueError(f"Validation failed: amount_safe_to_pay ({safe_amt}) out of bounds [0, {full_price}].")

        status = payload.get("affordability_status")
        valid_statuses = ["affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"]
        if status not in valid_statuses:
            raise ValueError(f"Validation failed: invalid affordability_status '{status}'.")

        method = payload.get("recommended_payment_method")
        valid_methods = ["full_payment", "partial_payment", "installments", "wait", "not_recommended"]
        if method not in valid_methods:
            raise ValueError(f"Validation failed: invalid recommended_payment_method '{method}'.")

        changes = payload.get("spending_changes_needed")
        if not isinstance(changes, list):
            raise ValueError("Validation failed: spending_changes_needed must be a list.")

        # Logic cross-consistency
        if status == "affordable_now":
            if method != "full_payment":
                raise ValueError("Validation failed: affordable_now requires recommended_payment_method = 'full_payment'.")
            if len(changes) > 0:
                raise ValueError("Validation failed: affordable_now cannot require spending changes.")

        if method == "not_recommended" and status != "not_affordable":
            raise ValueError("Validation failed: not_recommended payment method requires not_affordable status.")
