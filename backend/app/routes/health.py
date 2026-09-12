"""
Health Check & System Status Endpoint
"""

from datetime import datetime
from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
@router.get("/api/health")
def health_check():
    """System health endpoint."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model_configured": bool(settings.GEMINI_API_KEY),
    }
