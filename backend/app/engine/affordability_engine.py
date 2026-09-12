"""
Affordability & Safety Constraint Evaluator
Audits projected daily balance curves against safety buffer floor and non-negative cash limits.
"""

from typing import List, Dict, Any, Tuple, Optional
from app.models.decision import ViolationType
from app.utils.logger import logger


class AffordabilityEngine:
    """Verifies compliance with safety buffer, liquidity limits, and DTI thresholds."""

    @staticmethod
    def evaluate_safety(
        balance_curve: List[Dict[str, Any]], safety_buffer: float
    ) -> Tuple[bool, Optional[ViolationType], Optional[int], float]:
        """
        Audits daily balance curve.
        Returns: (is_safe, violation_type, violation_day_index, min_projected_balance)
        """
        if not balance_curve:
            return False, ViolationType.NEGATIVE_CASH_BREACH, 0, 0.0

        min_balance = float("inf")
        violation_type = None
        violation_day = None

        for day_idx, record in enumerate(balance_curve):
            bal = record.get("balance", 0.0)
            if bal < min_balance:
                min_balance = bal

            if bal < 0 and violation_type is None:
                violation_type = ViolationType.NEGATIVE_CASH_BREACH
                violation_day = day_idx

            elif bal < safety_buffer and violation_type is None:
                violation_type = ViolationType.SAFETY_BUFFER_BREACH
                violation_day = day_idx

        is_safe = violation_type is None
        return is_safe, violation_type, violation_day, min_balance
