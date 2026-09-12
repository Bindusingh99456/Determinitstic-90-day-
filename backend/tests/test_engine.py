"""
Unit tests for deterministic financial engines and affordability checks.
"""

from app.engine.affordability_engine import AffordabilityEngine
from app.models.decision import ViolationType


def test_affordability_safety_pass():
    balance_curve = [
        {"balance": 1500.0},
        {"balance": 1200.0},
        {"balance": 1100.0},
    ]
    is_safe, violation, day, min_bal = AffordabilityEngine.evaluate_safety(balance_curve, safety_buffer=1000.0)
    assert is_safe is True
    assert violation is None
    assert min_bal == 1100.0


def test_affordability_safety_breach():
    balance_curve = [
        {"balance": 1200.0},
        {"balance": 800.0},
        {"balance": 1100.0},
    ]
    is_safe, violation, day, min_bal = AffordabilityEngine.evaluate_safety(balance_curve, safety_buffer=1000.0)
    assert is_safe is False
    assert violation == ViolationType.SAFETY_BUFFER_BREACH
    assert day == 1
    assert min_bal == 800.0
