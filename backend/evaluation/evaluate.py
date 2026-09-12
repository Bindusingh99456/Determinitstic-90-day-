"""
Evaluation & Regression Benchmark Script
Runs backend decision engine against sample_requests.csv using Python standard library,
identifies mismatches, and verifies rule compliance across all fields.
"""

import os
import sys
import csv
from typing import List, Dict, Any, Tuple

# Ensure backend directory is in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models.requests import PurchaseRequest
from app.engine.decision_engine import DecisionEngine
from app.routes.decision import format_payment_plan_summary
from app.models.financial import (
    FinancialEvent,
    EventType,
    EventStatus,
)


def get_mock_user_events(request_id: str) -> Tuple[float, List[FinancialEvent]]:
    """Generates mock user account balance and events tailored for sample request evaluation."""
    if request_id == "R001":
        # Laptop $60k: Start balance $20k, buffer $10k. Salary $80k arrives 2026-09-30.
        events = [
            FinancialEvent(
                event_id="EVT_SALARY_001",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=80000.0,
                event_date="2026-09-30",
                category="SALARY",
            )
        ]
        return 20000.0, events

    elif request_id == "R002":
        # Smart Watch $800: Start balance $5k, buffer $1k. Safe today = $800 <= $4000.
        return 5000.0, []

    elif request_id == "R003":
        # TV $1,500: Start balance $1,800, buffer $1,000. Safe today = $800.
        events = [
            FinancialEvent(
                event_id="EVT_SALARY_14D_1",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-09-25",
                category="SALARY",
            ),
            FinancialEvent(
                event_id="EVT_SALARY_14D_2",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=2000.0,
                event_date="2026-10-09",
                category="SALARY",
            ),
        ]
        return 1800.0, events

    elif request_id == "R004":
        # Phone $1,000: Start balance $1,200, buffer $1,000. Safe today = $200.
        events = [
            FinancialEvent(
                event_id="EVT_SUB",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.EXPENSE,
                status=EventStatus.CONFIRMED,
                amount=200.0,
                event_date="2026-09-15",
                is_recurring=True,
                category="SUBSCRIPTION",
            ),
            FinancialEvent(
                event_id="EVT_SALARY_OCT",
                user_id="U1",
                account_id="ACC1",
                event_type=EventType.INCOME,
                status=EventStatus.CONFIRMED,
                amount=1000.0,
                event_date="2026-10-01",
                category="SALARY",
            )
        ]
        return 1200.0, events

    else:
        # Default R005 Vacation $50,000: Start balance $2000, buffer $1000. Safe today = $1000.
        return 2000.0, []


def evaluate_sample_requests(csv_path: str = "backend/app/data/sample_requests.csv") -> bool:
    """Runs evaluation benchmark against sample_requests.csv."""
    if not os.path.exists(csv_path):
        print(f"Sample requests CSV file not found at {csv_path}")
        return False

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"\n=======================================================")
    print(f"RUNNING BENCHMARK EVALUATION AGAINST {csv_path}")
    print(f"Total Test Requests: {len(rows)}")
    print(f"=======================================================\n")

    mismatches = []
    passed_count = 0

    for idx, row in enumerate(rows):
        req_id = str(row["request_id"]).strip()
        product = str(row["product"]).strip()
        amount = float(row["amount"])
        desired_date = str(row["desired_date"]).strip()

        start_balance, events = get_mock_user_events(req_id)

        internal_req = PurchaseRequest(
            request_id=req_id,
            user_id="U1",
            item_name=product,
            full_price=amount,
            offer_expires_at=desired_date,
        )

        res = DecisionEngine.evaluate_request(
            request=internal_req,
            start_balance=start_balance,
            events=events,
            as_of_date="2026-09-12",
        )

        # Format spending changes string
        raw_changes = res.get("spending_changes_needed", [])
        if not raw_changes:
            spending_changes_str = "none"
        elif isinstance(raw_changes, list):
            spending_changes_str = ", ".join(raw_changes)
        else:
            spending_changes_str = str(raw_changes)

        plan_str = format_payment_plan_summary(res.get("payment_plan"))

        actual = {
            "amount_safe_to_pay": res.get("amount_safe_to_pay", 0.0),
            "affordability_status": res.get("affordability_status"),
            "recommended_payment_method": res.get("recommended_payment_method"),
            "payment_plan": plan_str,
            "earliest_date_for_full_payment": res.get("earliest_date_for_full_payment") or desired_date,
            "spending_changes_needed": spending_changes_str,
        }

        expected = {
            "amount_safe_to_pay": float(row["expected_amount_safe_to_pay"]),
            "affordability_status": str(row["expected_affordability_status"]).strip(),
            "recommended_payment_method": str(row["expected_recommended_payment_method"]).strip(),
            "payment_plan": str(row["expected_payment_plan"]).strip(),
            "earliest_date_for_full_payment": str(row["expected_earliest_date_for_full_payment"]).strip(),
            "spending_changes_needed": str(row["expected_spending_changes_needed"]).strip(),
        }

        request_passed = True
        request_mismatches = []

        for field, exp_val in expected.items():
            act_val = actual.get(field)
            if field == "amount_safe_to_pay":
                if abs(float(act_val) - float(exp_val)) > 0.01:
                    request_passed = False
                    request_mismatches.append((field, exp_val, act_val))
            else:
                if str(act_val).strip() != str(exp_val).strip():
                    request_passed = False
                    request_mismatches.append((field, exp_val, act_val))

        if request_passed:
            passed_count += 1
            print(f"✓ Request {req_id} ({product}): PASSED ALL FIELDS")
        else:
            print(f"✗ Request {req_id} ({product}): MISMATCH DETECTED")
            for field, exp_val, act_val in request_mismatches:
                print(f"    - Field '{field}': Expected '{exp_val}', Got '{act_val}'")
                mismatches.append({
                    "request_id": req_id,
                    "product": product,
                    "field": field,
                    "expected": exp_val,
                    "actual": act_val,
                })

    print(f"\n-------------------------------------------------------")
    print(f"BENCHMARK SUMMARY: {passed_count}/{len(rows)} PASSED ({(passed_count/len(rows))*100:.1f}%)")
    print(f"-------------------------------------------------------\n")

    return len(mismatches) == 0


if __name__ == "__main__":
    success = evaluate_sample_requests()
    if not success:
        sys.exit(1)
