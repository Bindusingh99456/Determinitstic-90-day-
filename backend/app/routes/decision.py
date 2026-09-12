"""
Decision API Router for Stitch Frontend
Endpoints:
- POST /api/decision (Evaluates purchase request and returns deterministic decision)
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, File, UploadFile, Form, status
from app.models.requests import PurchaseRequest
from app.models.decision import StitchDecisionRequest, StitchDecisionResponse
from app.models.evidence import ExtractedFact
from app.engine.decision_engine import DecisionEngine
from app.services.data_service import DataService
from app.ai.image_analyzer import ImageAnalyzer
from app.utils.logger import logger

router = APIRouter(tags=["Decision Engine"])

data_service = DataService()
image_analyzer = ImageAnalyzer()


def format_payment_plan_summary(plan_data: Any) -> str:
    """Formats payment plan into concise string summary e.g. '2026-09-30:60000'."""
    if not plan_data:
        return "none"

    if isinstance(plan_data, str):
        return plan_data

    if isinstance(plan_data, dict):
        dates = plan_data.get("payment_dates", [])
        amounts = plan_data.get("payment_amounts", [])
        if dates and amounts and len(dates) == len(amounts):
            parts = []
            for d, a in zip(dates, amounts):
                amt_val = float(a)
                amt_str = f"{int(amt_val)}" if amt_val.is_integer() else f"{amt_val:.2f}"
                parts.append(f"{d}:{amt_str}")
            return ", ".join(parts)

        completion_date = plan_data.get("completion_date")
        total_amt = plan_data.get("total_payable_amount", 0.0)
        if completion_date and total_amt:
            amt_str = f"{int(total_amt)}" if float(total_amt).is_integer() else f"{total_amt:.2f}"
            return f"{completion_date}:{amt_str}"

    return "none"


@router.post("/api/decision", response_model=StitchDecisionResponse, status_code=status.HTTP_200_OK)
def evaluate_decision(req: StitchDecisionRequest) -> StitchDecisionResponse:
    """
    Evaluates purchase request and returns full Stitch decision payload.
    No financial calculations are performed on the frontend.
    """
    try:
        # Determine product name and full price
        product_name = req.product or req.item_name or "Requested Item"
        price = req.amount if req.amount is not None else (req.full_price if req.full_price is not None else 0.0)

        if price < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Purchase amount cannot be negative.",
            )

        # Generate or use request_id
        request_id = req.request_id or data_service.generate_next_request_id()
        user_id = req.user_id or "USER_DEFAULT"
        desired_date = req.desired_date or req.offer_expires_at

        # Construct PurchaseRequest for DecisionEngine
        internal_req = PurchaseRequest(
            request_id=request_id,
            user_id=user_id,
            item_name=product_name,
            full_price=price,
            offer_expires_at=desired_date,
        )

        # Retrieve user profile & financial events
        user_profile = data_service.get_user_profile(user_id)
        events = data_service.get_user_events(user_id)

        # Default starting balance if no profile
        start_balance = user_profile if user_profile else 50000.0

        # Execute deterministic decision engine
        raw_decision = DecisionEngine.evaluate_request(
            request=internal_req,
            start_balance=start_balance,
            events=events,
            as_of_date="2026-09-12",
        )

        # Format spending changes string
        raw_changes = raw_decision.get("spending_changes_needed", [])
        if not raw_changes:
            spending_changes_str = "none"
        elif isinstance(raw_changes, list):
            spending_changes_str = ", ".join(raw_changes)
        else:
            spending_changes_str = str(raw_changes)

        # Format payment plan string
        raw_plan = raw_decision.get("payment_plan")
        plan_summary = format_payment_plan_summary(raw_plan)

        # Build final response payload
        response_payload = {
            "request_id": request_id,
            "amount_safe_to_pay": raw_decision.get("amount_safe_to_pay", 0.0),
            "affordability_status": raw_decision.get("affordability_status", "not_affordable"),
            "recommended_payment_method": raw_decision.get("recommended_payment_method", "not_recommended"),
            "payment_plan": plan_summary,
            "earliest_date_for_full_payment": raw_decision.get("earliest_date_for_full_payment") or desired_date or "2026-09-12",
            "spending_changes_needed": spending_changes_str,
            "decision_explanation": raw_decision.get("decision_explanation", ""),
        }

        # Store in decision history repository
        data_service.save_decision(request_id, response_payload)

        return StitchDecisionResponse(**response_payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error evaluating decision request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during financial decision evaluation.",
        )


@router.post("/api/decision/evidence/parse-image", response_model=List[ExtractedFact])
async def parse_evidence_image(
    file: UploadFile = File(...), target_event_id: Optional[str] = Form(None)
):
    """Parses receipt/paystub/quote image and returns extracted facts."""
    try:
        content = await file.read()
        facts = image_analyzer.analyze_image("IMG_UPLOAD", content, file.content_type, target_event_id)
        return facts
    except Exception as e:
        logger.error(f"Error parsing evidence image: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse evidence image.",
        )
