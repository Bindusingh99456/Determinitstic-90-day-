"""
Purchase Requests History Router
Endpoints:
- GET /api/requests (Returns request decision history list)
- GET /api/requests/{request_id} (Returns complete decision for one request)
"""

from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, status
from app.models.decision import StitchDecisionResponse
from app.services.data_service import DataService
from app.utils.logger import logger

router = APIRouter(prefix="/api/requests", tags=["Purchase Requests"])

data_service = DataService()


@router.get("", response_model=List[StitchDecisionResponse], status_code=status.HTTP_200_OK)
@router.get("/", response_model=List[StitchDecisionResponse], status_code=status.HTTP_200_OK)
def get_request_history() -> List[Dict[str, Any]]:
    """Retrieves list of all decision records in request history."""
    try:
        decisions = data_service.get_all_decisions()
        return decisions
    except Exception as e:
        logger.error(f"Error fetching request history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve request history.",
        )


@router.get("/{request_id}", response_model=StitchDecisionResponse, status_code=status.HTTP_200_OK)
def get_single_request_decision(request_id: str) -> Dict[str, Any]:
    """Retrieves the complete decision for a single request_id."""
    try:
        decision = data_service.get_decision(request_id)
        if not decision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request decision for ID '{request_id}' not found.",
            )
        return decision
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching decision for request {request_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving request decision.",
        )
