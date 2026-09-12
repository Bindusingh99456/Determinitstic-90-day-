"""
Unit tests for Spending Optimizer Engine (SpendingOptimizer)
Tests:
- Flexible vs Essential expense identification
- Prohibition of modifying essential expenses, debt obligations, taxes, utilities, groceries, rent
- Generation of candidate actions (stop:<event_id> and reduce_to:<event_id>:<new_amount>)
- Mutual exclusivity of stop and reduce_to for the same event
- Financial impact calculation and 90-day forecast re-simulation
- Filtering of useless changes (discarding changes that do not improve safety/wait days)
- Max 3 changes cap
- Deterministic ranking rules (immediate safety today > minimal wait days > minimal financial disruption > fewest actions)
"""

import unittest
from datetime import date
from app.models.financial import (
    UserFinancialProfile,
    FinancialAccount,
    FinancialEvent,
    AccountType,
    EventType,
    EventStatus,
)
from app.engine.spending_optimizer import (
    SpendingOptimizer,
    ActionType,
    SpendingChange,
    SpendingOptimizationResult,
)


class TestSpendingOptimizer(unittest.TestCase):

    def setUp(self):
        self.as_of_date = "2026-09-12"

    def test_1_essential_expenses_never_modified(self):
        """Essential expenses (Rent, Groceries, Utilities, Debt) must NEVER be modified."""
        rent_event = FinancialEvent(
            event_id="EVT_RENT",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=1500.0,
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="RENT",
        )

        util_event = FinancialEvent(
            event_id="EVT_UTIL",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=150.0,
            event_date="2026-09-05",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="UTILITIES_ELECTRICITY",
        )

        debt_event = FinancialEvent(
            event_id="EVT_DEBT",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=250.0,
            event_date="2026-09-10",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="CREDIT_CARD_DEBT",
        )

        self.assertFalse(SpendingOptimizer.is_flexible_recurring_expense(rent_event))
        self.assertFalse(SpendingOptimizer.is_flexible_recurring_expense(util_event))
        self.assertFalse(SpendingOptimizer.is_flexible_recurring_expense(debt_event))

        events = [rent_event, util_event, debt_event]
        candidates = SpendingOptimizer.generate_candidate_actions(events)
        self.assertEqual(len(candidates), 0, "No essential expenses should produce candidate actions!")

    def test_2_flexible_recurring_expenses_identified(self):
        """Flexible recurring expenses (Streaming, Gym, Dining Out) should produce candidate actions."""
        netflix = FinancialEvent(
            event_id="EVT_NETFLIX",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=20.0,
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="STREAMING_SUBSCRIPTION",
        )

        gym = FinancialEvent(
            event_id="EVT_GYM",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=60.0,
            event_date="2026-09-05",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="FITNESS_GYM",
        )

        self.assertTrue(SpendingOptimizer.is_flexible_recurring_expense(netflix))
        self.assertTrue(SpendingOptimizer.is_flexible_recurring_expense(gym))

        candidates = SpendingOptimizer.generate_candidate_actions([netflix, gym])
        # Each flexible event produces 2 actions: stop and reduce_to (50%)
        self.assertEqual(len(candidates), 4)

        action_strs = [c.action_str for c in candidates]
        self.assertIn("stop:EVT_NETFLIX", action_strs)
        self.assertIn("reduce_to:EVT_NETFLIX:10.00", action_strs)
        self.assertIn("stop:EVT_GYM", action_strs)
        self.assertIn("reduce_to:EVT_GYM:30.00", action_strs)

    def test_3_stop_and_reduce_to_mutually_exclusive_per_event(self):
        """Optimizer must NEVER return both stop:EVT_1 and reduce_to:EVT_1 in the same recommendation."""
        # User balance = $1,100, Buffer = $1,000. Wants to buy $500 item.
        # Gym = $100/mo flexible expense. Stopping Gym ($100 savings) makes purchase safe today.
        gym = FinancialEvent(
            event_id="EVT_GYM",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=100.0,
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="GYM_MEMBERSHIP",
        )

        result = SpendingOptimizer.optimize_spending_changes(
            requested_amount=500.0,
            start_balance=1100.0,
            events=[gym],
            as_of_date=self.as_of_date,
        )

        # Check mutual exclusivity
        event_ids = [c.event_id for c in result.recommended_changes]
        self.assertEqual(len(event_ids), len(set(event_ids)), "Event IDs in recommended changes must be unique!")

    def test_4_useless_changes_discarded(self):
        """Changes that do not improve safety or reduce wait days must be discarded."""
        # User starting balance = $5,000, buffer = $1,000. Wants to buy $100 item.
        # Purchase is ALREADY 100% safe today without any spending changes.
        netflix = FinancialEvent(
            event_id="EVT_NETFLIX",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=20.0,
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="STREAMING",
        )

        result = SpendingOptimizer.optimize_spending_changes(
            requested_amount=100.0,
            start_balance=5000.0,
            events=[netflix],
            as_of_date=self.as_of_date,
        )

        # Since baseline is already safe today, no changes should be recommended!
        self.assertEqual(len(result.recommended_changes), 0)
        self.assertEqual(result.total_monthly_savings, 0.0)
        self.assertTrue(result.optimized_safe_today)

    def test_5_max_three_changes_returned(self):
        """Optimizer must return at most 3 changes."""
        # Create 5 flexible recurring expenses
        events = []
        for i in range(5):
            events.append(
                FinancialEvent(
                    event_id=f"EVT_FLEX_{i}",
                    user_id="U1",
                    account_id="ACC1",
                    event_type=EventType.EXPENSE,
                    status=EventStatus.CONFIRMED,
                    amount=50.0,
                    event_date="2026-09-01",
                    is_recurring=True,
                    recurrence_pattern="MONTHLY",
                    category=f"ENTERTAINMENT_{i}",
                )
            )

        result = SpendingOptimizer.optimize_spending_changes(
            requested_amount=800.0,
            start_balance=1200.0,  # Buffer = 1000, Headroom = 200. Short by 600.
            events=events,
            as_of_date=self.as_of_date,
            max_changes=3,
        )

        self.assertTrue(len(result.recommended_changes) <= 3)

    def test_6_deterministic_ranking_prefers_least_disruption(self):
        """
        If stopping streaming ($20) makes purchase safe today, and stopping dining out ($200) also makes it safe,
        optimizer chooses the minimal cutback ($20) to minimize lifestyle disruption.
        """
        # User balance = $1,490, Buffer = $1,000 -> Headroom = $490.
        # Purchase = $500 (Short by $10).
        streaming = FinancialEvent(
            event_id="EVT_STREAM",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=20.0,  # $20 savings is sufficient to cover the $10 gap
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="STREAMING",
        )

        dining = FinancialEvent(
            event_id="EVT_DINING",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=200.0,  # $200 savings is also sufficient, but causes higher disruption
            event_date="2026-09-01",
            is_recurring=True,
            recurrence_pattern="MONTHLY",
            category="DINING_OUT",
        )

        result = SpendingOptimizer.optimize_spending_changes(
            requested_amount=500.0,
            start_balance=1490.0,
            events=[streaming, dining],
            as_of_date=self.as_of_date,
        )

        self.assertTrue(result.optimized_safe_today)
        self.assertEqual(len(result.recommended_changes), 1)
        # Should pick streaming ($20 cutback) over dining ($200 cutback)
        self.assertEqual(result.recommended_changes[0].event_id, "EVT_STREAM")
        self.assertEqual(result.total_monthly_savings, 20.0)

    def test_7_historical_non_recurring_transactions_ignored(self):
        """Historical past transactions and non-recurring expenses must be ignored."""
        past_event = FinancialEvent(
            event_id="EVT_PAST_SHOPPING",
            user_id="U1",
            account_id="ACC1",
            event_type=EventType.EXPENSE,
            status=EventStatus.CONFIRMED,
            amount=500.0,
            event_date="2026-08-01",
            is_recurring=False,  # NOT RECURRING
            category="SHOPPING",
        )

        self.assertFalse(SpendingOptimizer.is_flexible_recurring_expense(past_event))


if __name__ == "__main__":
    unittest.main()
