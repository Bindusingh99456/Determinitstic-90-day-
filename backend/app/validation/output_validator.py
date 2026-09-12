"""
Output Compliance & Zero-Hallucination Validator
Audits generated decision objects against strict competition schema rules and mathematical boundaries.
"""

from typing import Tuple, List
from app.models.decision import DecisionResponse
from app.utils.logger import logger


class OutputValidator:
    """Verifies that decision output payloads satisfy competition rules."""

    @staticmethod
    def validate_decision(decision: DecisionResponse) -> Tuple[bool, List[str]]:
        """
        Audits a decision payload.
        Returns (is_valid, list_of_violations).
        """
        violations: List[str] = []

        # 1. Non-negative cash constraint check
        if decision.decision.recommendation in ["BUY_NOW_UPFRONT", "BUY_NOW_PAYMENT_PLAN"]:
            if decision.metrics.projected_90d_min_balance_if_purchased_now < 0:
                violations.append("Recommendation recommends purchase despite negative projected cash flow.")

        # 2. Safety buffer breach check
        if decision.decision.recommendation == "BUY_NOW_UPFRONT":
            if decision.metrics.projected_90d_min_balance_if_purchased_now < decision.metrics.required_safety_buffer:
                violations.append("BUY_NOW_UPFRONT approved while breaching emergency safety buffer.")

        # 3. Wait days consistency check
        if decision.decision.recommendation == "WAIT" and decision.decision.optimal_wait_days <= 0:
            violations.append("WAIT recommendation must specify optimal_wait_days > 0.")

        is_valid = len(violations) == 0
        if not is_valid:
            logger.error(f"Validation failed for request {decision.request_id}: {violations}")

        return is_valid, violations
