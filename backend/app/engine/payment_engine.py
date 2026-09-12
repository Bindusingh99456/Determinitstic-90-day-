"""
Payment Plan & Financing Engine
Generates payment schedules, installment options, partial payments, wait plans,
calculates financing fees, and runs 90-day safety simulations for candidate payment options.
"""

import os
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple, Optional, Union
import pandas as pd

from app.models.financial import UserFinancialProfile, FinancialState, FinancialEvent
from app.models.requests import PurchaseRequest, PaymentOption, PaymentOptionType, PaymentMethod, PaymentPlan
from app.models.evidence import ExtractedFact
from app.engine.forecast_engine import ForecastEngine, convert_to_base_currency
from app.engine.amount_safe_engine import AmountSafeEngine
from app.utils.date_helpers import parse_date
from app.utils.logger import logger


class PaymentEngine:
    """Calculates effective costs, generates schedules, and evaluates payment plans against 90-day safety rules."""

    @staticmethod
    def generate_payment_schedule(
        option: PaymentOption, execution_date: Union[str, date]
    ) -> List[Tuple[date, float, str]]:
        """
        Generates list of (payment_date, amount, description) cash outflows.
        Down payment (if any) debited on execution_date.
        Installments debited on execution_date + k * frequency_days.
        """
        exec_d = parse_date(execution_date)
        schedule: List[Tuple[date, float, str]] = []

        if option.type == PaymentOptionType.UPFRONT:
            upfront_amt = option.down_payment if option.down_payment > 0 else option.installment_amount
            total_upfront = upfront_amt + option.upfront_fee
            schedule.append((exec_d, total_upfront, f"Upfront Payment ({option.option_id})"))
            return schedule

        # Down payment for installments
        if option.down_payment > 0 or option.upfront_fee > 0:
            schedule.append(
                (exec_d, option.down_payment + option.upfront_fee, f"Down Payment ({option.option_id})")
            )

        # Installments
        for i in range(option.num_installments):
            installment_date = exec_d + timedelta(days=(i + 1) * option.frequency_days)
            schedule.append(
                (
                    installment_date,
                    option.installment_amount,
                    f"Installment {i+1}/{option.num_installments} ({option.option_id})",
                )
            )

        return schedule

    @staticmethod
    def calculate_total_effective_cost(option: PaymentOption, full_price: float = 0.0) -> float:
        """Computes total cost including down payment, fees, and installments."""
        if option.type == PaymentOptionType.UPFRONT:
            base = option.down_payment if option.down_payment > 0 else (full_price or option.installment_amount)
            return base + option.upfront_fee
        return option.down_payment + option.upfront_fee + (option.num_installments * option.installment_amount)

    @staticmethod
    def load_options_from_csv(source: Union[str, pd.DataFrame]) -> List[PaymentOption]:
        """
        Reads available payment options from CSV file path or pandas DataFrame (e.g. request_payment_options.csv).
        """
        if isinstance(source, str):
            if not os.path.exists(source):
                logger.warning(f"Payment options CSV path '{source}' does not exist.")
                return []
            df = pd.read_csv(source)
        else:
            df = source

        options: List[PaymentOption] = []
        for _, row in df.iterrows():
            opt_id = str(row.get("option_id", "")).strip()
            type_str = str(row.get("type", "UPFRONT")).strip().upper()

            try:
                opt_type = PaymentOptionType(type_str)
            except ValueError:
                opt_type = PaymentOptionType.UPFRONT

            down = float(row.get("down_payment", 0.0) or 0.0)
            inst_amt = float(row.get("installment_amount", 0.0) or 0.0)
            num_inst = int(row.get("num_installments", 1) or 1)
            freq = int(row.get("frequency_days", 30) or 30)
            fee = float(row.get("upfront_fee", 0.0) or 0.0)
            apr = float(row.get("apr_percent", 0.0) or 0.0)
            allows_partial = bool(row.get("allows_partial_payment", False))

            opt = PaymentOption(
                option_id=opt_id,
                type=opt_type,
                down_payment=down,
                installment_amount=inst_amt,
                num_installments=num_inst,
                frequency_days=freq,
                upfront_fee=fee,
                apr_percent=apr,
                allows_partial_payment=allows_partial,
            )
            options.append(opt)
        return options

    # --- Individual Plan Evaluators ---

    @classmethod
    def evaluate_full_payment(
        cls,
        requested_amount: float,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        upfront_fee: float = 0.0,
        option_id: Optional[str] = "OPT_FULL",
    ) -> PaymentPlan:
        """Evaluates full upfront payment today."""
        start_date_obj = parse_date(start_date)
        total_payable = round(requested_amount + upfront_fee, 2)
        payment_dates = [start_date_obj.strftime("%Y-%m-%d")]
        payment_amounts = [total_payable]
        schedule_tuples = [(start_date_obj, total_payable, "Full Upfront Payment")]

        forecast = ForecastEngine(
            start_balance=start_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            events=events,
            facts=facts,
        )

        curve = forecast.simulate_90day_balance_curve(additional_outflows=schedule_tuples)
        min_bal = min(r["balance"] for r in curve)

        is_safe = min_bal >= forecast.minimum_balance_to_keep and min_bal >= 0.0
        rejection_reasons = []
        if not is_safe:
            rejection_reasons.append(
                f"Full payment breaches minimum balance threshold (${min_bal:.2f} < ${forecast.minimum_balance_to_keep:.2f})"
            )

        violates_deadline = False
        if completion_deadline:
            deadline_obj = parse_date(completion_deadline)
            if start_date_obj > deadline_obj:
                violates_deadline = True
                is_safe = False
                rejection_reasons.append("Full payment date violates completion deadline.")

        return PaymentPlan(
            plan_id=f"PLAN_FULL_{option_id or 'DEFAULT'}",
            method=PaymentMethod.FULL_PAYMENT if is_safe else PaymentMethod.NOT_RECOMMENDED,
            option_id=option_id,
            description=f"Full payment of ${total_payable:.2f} today",
            total_payable_amount=total_payable,
            financing_fees=round(upfront_fee, 2),
            payment_dates=payment_dates,
            payment_amounts=payment_amounts,
            schedule=[(d, amt, desc) for d, amt, desc in payment_amounts_to_schedule(payment_dates, payment_amounts, ["Full Upfront Payment"])],
            is_safe=is_safe,
            is_valid=True,
            rejection_reasons=rejection_reasons,
            minimum_projected_balance=round(min_bal, 2),
            completion_date=start_date_obj.strftime("%Y-%m-%d"),
            violates_completion_deadline=violates_deadline,
        )

    @classmethod
    def evaluate_partial_payment(
        cls,
        requested_amount: float,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        allows_partial_payment: bool = True,
        user_accepts_partial_payment: bool = True,
        second_payment_date: Optional[Union[str, date]] = None,
        option_id: Optional[str] = "OPT_PARTIAL",
    ) -> PaymentPlan:
        """
        Evaluates partial payment plan following exact challenge rules:
        - request must allow partial payment
        - user must accept partial payment
        - safe amount > 0
        - safe amount < requested amount
        - full payment must be possible by desired completion date
        - exactly two payments
        - first payment is today
        - second payment is the remaining amount
        - amounts must sum exactly to requested amount
        """
        start_date_obj = parse_date(start_date)
        rejection_reasons: List[str] = []
        is_valid = True

        # Rule 1 & 2: Permissions
        if not allows_partial_payment:
            is_valid = False
            rejection_reasons.append("Request does not allow partial payments.")

        if not user_accepts_partial_payment:
            is_valid = False
            rejection_reasons.append("User does not accept partial payments.")

        # Calculate safe amount today
        safe_amt_today = AmountSafeEngine.calculate_amount_safe_to_pay(
            start_balance=start_balance,
            requested_amount=requested_amount,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            completion_deadline=completion_deadline,
            events=events,
            facts=facts,
        )

        # Rule 3 & 4: Safe amount boundaries
        if safe_amt_today <= 0:
            is_valid = False
            rejection_reasons.append(f"Amount safe to pay today (${safe_amt_today:.2f}) must be > 0.")

        if safe_amt_today >= requested_amount:
            is_valid = False
            rejection_reasons.append(
                f"Amount safe to pay today (${safe_amt_today:.2f}) is >= requested amount (${requested_amount:.2f}). Partial payment unnecessary."
            )

        # Determine second payment date (completion deadline or fallback 30d)
        if second_payment_date:
            p2_date_obj = parse_date(second_payment_date)
        elif completion_deadline:
            p2_date_obj = parse_date(completion_deadline)
        else:
            p2_date_obj = start_date_obj + timedelta(days=30)

        # Rule 5 & 6 & 7 & 8 & 9: Amounts and Dates
        p1_amount = round(safe_amt_today, 2)
        p2_amount = round(requested_amount - p1_amount, 2)

        payment_dates = [start_date_obj.strftime("%Y-%m-%d"), p2_date_obj.strftime("%Y-%m-%d")]
        payment_amounts = [p1_amount, p2_amount]

        # Verify exact sum rule
        if round(p1_amount + p2_amount, 2) != round(requested_amount, 2):
            is_valid = False
            rejection_reasons.append("Payment amounts do not sum exactly to requested amount.")

        # Check completion deadline
        violates_deadline = False
        if completion_deadline:
            deadline_obj = parse_date(completion_deadline)
            if p2_date_obj > deadline_obj:
                violates_deadline = True
                is_valid = False
                rejection_reasons.append(
                    f"Second payment date ({p2_date_obj}) violates completion deadline ({deadline_obj})."
                )

        # Run 90-day safety simulation with both payments
        schedule_tuples = [
            (start_date_obj, p1_amount, "Partial Payment 1 (Today)"),
            (p2_date_obj, p2_amount, "Partial Payment 2 (Final)"),
        ]

        forecast = ForecastEngine(
            start_balance=start_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            events=events,
            facts=facts,
        )

        days_ahead = max(90, (p2_date_obj - start_date_obj).days)
        curve = forecast.simulate_90day_balance_curve(additional_outflows=schedule_tuples, horizon_days=days_ahead)
        min_bal = min(r["balance"] for r in curve)

        is_safe = is_valid and (min_bal >= forecast.minimum_balance_to_keep) and (min_bal >= 0.0)
        if is_valid and not is_safe:
            rejection_reasons.append(
                f"Partial payment plan breaches safety buffer (${min_bal:.2f} < ${forecast.minimum_balance_to_keep:.2f})."
            )

        return PaymentPlan(
            plan_id=f"PLAN_PARTIAL_{option_id or 'DEFAULT'}",
            method=PaymentMethod.PARTIAL_PAYMENT if is_safe else PaymentMethod.NOT_RECOMMENDED,
            option_id=option_id,
            description=f"Partial payment: ${p1_amount:.2f} today, ${p2_amount:.2f} on {p2_date_obj.strftime('%Y-%m-%d')}",
            total_payable_amount=round(requested_amount, 2),
            financing_fees=0.0,
            payment_dates=payment_dates,
            payment_amounts=payment_amounts,
            schedule=[
                (start_date_obj.strftime("%Y-%m-%d"), p1_amount, "Partial Payment 1 (Today)"),
                (p2_date_obj.strftime("%Y-%m-%d"), p2_amount, f"Partial Payment 2 ({p2_date_obj.strftime('%Y-%m-%d')})"),
            ],
            is_safe=is_safe,
            is_valid=is_valid,
            rejection_reasons=rejection_reasons,
            minimum_projected_balance=round(min_bal, 2),
            completion_date=p2_date_obj.strftime("%Y-%m-%d"),
            violates_completion_deadline=violates_deadline,
        )

    @classmethod
    def evaluate_installments(
        cls,
        option: PaymentOption,
        requested_amount: float,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
    ) -> PaymentPlan:
        """Evaluates an installment option (BNPL or Credit Card)."""
        start_date_obj = parse_date(start_date)
        schedule_tuples = cls.generate_payment_schedule(option, start_date_obj)

        payment_dates = [d.strftime("%Y-%m-%d") for d, amt, desc in schedule_tuples]
        payment_amounts = [round(amt, 2) for d, amt, desc in schedule_tuples]
        total_payable = round(sum(payment_amounts), 2)
        financing_fees = round(max(0.0, total_payable - requested_amount), 2)

        completion_date_obj = schedule_tuples[-1][0] if schedule_tuples else start_date_obj

        violates_deadline = False
        rejection_reasons: List[str] = []
        if completion_deadline:
            deadline_obj = parse_date(completion_deadline)
            if completion_date_obj > deadline_obj:
                violates_deadline = True
                rejection_reasons.append(
                    f"Installment completion date ({completion_date_obj}) exceeds deadline ({deadline_obj})."
                )

        forecast = ForecastEngine(
            start_balance=start_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            events=events,
            facts=facts,
        )

        days_ahead = max(90, (completion_date_obj - start_date_obj).days)
        curve = forecast.simulate_90day_balance_curve(additional_outflows=schedule_tuples, horizon_days=days_ahead)
        min_bal = min(r["balance"] for r in curve)

        is_safe = (not violates_deadline) and (min_bal >= forecast.minimum_balance_to_keep) and (min_bal >= 0.0)
        if not is_safe and not violates_deadline:
            rejection_reasons.append(
                f"Installments plan breaches safety buffer (${min_bal:.2f} < ${forecast.minimum_balance_to_keep:.2f})."
            )

        return PaymentPlan(
            plan_id=f"PLAN_INST_{option.option_id}",
            method=PaymentMethod.INSTALLMENTS if is_safe else PaymentMethod.NOT_RECOMMENDED,
            option_id=option.option_id,
            description=f"Installment plan ({option.num_installments} payments of ${option.installment_amount:.2f})",
            total_payable_amount=total_payable,
            financing_fees=financing_fees,
            payment_dates=payment_dates,
            payment_amounts=payment_amounts,
            schedule=[(d.strftime("%Y-%m-%d"), amt, desc) for d, amt, desc in schedule_tuples],
            is_safe=is_safe,
            is_valid=True,
            rejection_reasons=rejection_reasons,
            minimum_projected_balance=round(min_bal, 2),
            completion_date=completion_date_obj.strftime("%Y-%m-%d"),
            violates_completion_deadline=violates_deadline,
        )

    @classmethod
    def evaluate_wait(
        cls,
        requested_amount: float,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        minimum_balance_to_keep: float = 1000.0,
        start_date: Union[str, date] = "2026-09-12",
        completion_deadline: Optional[Union[str, date]] = None,
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        max_wait_days: int = 90,
    ) -> PaymentPlan:
        """Evaluates waiting until earliest safe execution date for full payment."""
        start_date_obj = parse_date(start_date)

        forecast = ForecastEngine(
            start_balance=start_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            start_date=start_date_obj,
            events=events,
            facts=facts,
        )

        safe_date_str = forecast.first_safe_full_payment_date(
            full_price=requested_amount, max_wait_days=max_wait_days
        )

        rejection_reasons: List[str] = []
        is_safe = False
        violates_deadline = False

        if not safe_date_str:
            rejection_reasons.append(f"No safe full payment date found within {max_wait_days} days.")
            safe_exec_d = start_date_obj
        else:
            safe_exec_d = parse_date(safe_date_str)
            is_safe = True

            if completion_deadline:
                deadline_obj = parse_date(completion_deadline)
                if safe_exec_d > deadline_obj:
                    violates_deadline = True
                    is_safe = False
                    rejection_reasons.append(
                        f"Earliest safe execution date ({safe_exec_d}) exceeds completion deadline ({deadline_obj})."
                    )

        # Simulate min balance if executed on safe_exec_d
        schedule_tuples = [(safe_exec_d, requested_amount, "Deferred Full Payment")]
        days_ahead = max(90, (safe_exec_d - start_date_obj).days + 90)
        curve = forecast.simulate_90day_balance_curve(additional_outflows=schedule_tuples, horizon_days=days_ahead)
        min_bal = min(r["balance"] for r in curve)

        return PaymentPlan(
            plan_id="PLAN_WAIT",
            method=PaymentMethod.WAIT if is_safe else PaymentMethod.NOT_RECOMMENDED,
            option_id="OPT_WAIT",
            description=f"Wait until {safe_exec_d.strftime('%Y-%m-%d')} for full payment",
            total_payable_amount=round(requested_amount, 2),
            financing_fees=0.0,
            payment_dates=[safe_exec_d.strftime("%Y-%m-%d")],
            payment_amounts=[round(requested_amount, 2)],
            schedule=[(safe_exec_d.strftime("%Y-%m-%d"), round(requested_amount, 2), "Deferred Full Payment")],
            is_safe=is_safe,
            is_valid=True,
            rejection_reasons=rejection_reasons,
            minimum_projected_balance=round(min_bal, 2),
            completion_date=safe_exec_d.strftime("%Y-%m-%d"),
            violates_completion_deadline=violates_deadline,
        )

    # --- Comprehensive Evaluator ---

    @classmethod
    def evaluate_all_plans(
        cls,
        request: PurchaseRequest,
        start_balance: Union[float, FinancialState, UserFinancialProfile],
        events: Optional[List[FinancialEvent]] = None,
        facts: Optional[List[ExtractedFact]] = None,
        as_of_date: Union[str, date] = "2026-09-12",
        options_override: Optional[List[PaymentOption]] = None,
    ) -> List[PaymentPlan]:
        """
        Evaluates all candidate payment options (full_payment, partial_payment, installments, wait)
        against 90-day cashflow safety simulation.
        Returns list of all evaluated PaymentPlan objects.
        """
        start_date_obj = parse_date(as_of_date)
        req_amount = request.full_price
        completion_deadline = request.offer_expires_at

        # Determine minimum balance to keep
        if isinstance(start_balance, UserFinancialProfile):
            min_buffer = start_balance.minimum_safety_buffer or 1000.0
        elif isinstance(start_balance, FinancialState):
            min_buffer = start_balance.minimum_balance_to_keep
        else:
            min_buffer = 1000.0

        plans: List[PaymentPlan] = []
        options = options_override or request.payment_options or []

        # 1. Evaluate Upfront Full Payment
        upfront_opts = [o for o in options if o.type == PaymentOptionType.UPFRONT]
        upfront_fee = upfront_opts[0].upfront_fee if upfront_opts else 0.0
        full_plan = cls.evaluate_full_payment(
            requested_amount=req_amount,
            start_balance=start_balance,
            minimum_balance_to_keep=min_buffer,
            start_date=start_date_obj,
            completion_deadline=completion_deadline,
            events=events,
            facts=facts,
            upfront_fee=upfront_fee,
        )
        plans.append(full_plan)

        # 2. Evaluate Installment Options
        inst_opts = [o for o in options if o.type in [PaymentOptionType.BNPL_INSTALLMENTS, PaymentOptionType.CREDIT_CARD]]
        for opt in inst_opts:
            inst_plan = cls.evaluate_installments(
                option=opt,
                requested_amount=req_amount,
                start_balance=start_balance,
                minimum_balance_to_keep=min_buffer,
                start_date=start_date_obj,
                completion_deadline=completion_deadline,
                events=events,
                facts=facts,
            )
            plans.append(inst_plan)

        # 3. Evaluate Partial Payment Plan
        allows_partial = request.allows_partial_payment or any(o.allows_partial_payment for o in options)
        partial_plan = cls.evaluate_partial_payment(
            requested_amount=req_amount,
            start_balance=start_balance,
            minimum_balance_to_keep=min_buffer,
            start_date=start_date_obj,
            completion_deadline=completion_deadline,
            events=events,
            facts=facts,
            allows_partial_payment=allows_partial,
            user_accepts_partial_payment=request.user_accepts_partial_payment,
        )
        plans.append(partial_plan)

        # 4. Evaluate Wait Plan
        wait_plan = cls.evaluate_wait(
            requested_amount=req_amount,
            start_balance=start_balance,
            minimum_balance_to_keep=min_buffer,
            start_date=start_date_obj,
            completion_deadline=completion_deadline,
            events=events,
            facts=facts,
        )
        plans.append(wait_plan)

        return plans


def payment_amounts_to_schedule(dates: List[str], amounts: List[float], descriptions: List[str]) -> List[Tuple[date, float, str]]:
    """Helper to pair date strings, amounts, and descriptions into tuples."""
    result = []
    for d_str, amt, desc in zip(dates, amounts, descriptions):
        result.append((parse_date(d_str), float(amt), str(desc)))
    return result
