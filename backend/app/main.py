"""
FastAPI Main Application Entrypoint
Configures REST API routes, CORS middleware, global exception handlers,
and structured error formatting for Stitch frontend integration.
"""

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes.health import router as health_router
from app.routes.requests import router as requests_router
from app.routes.decision import router as decision_router
from app.utils.logger import logger

app = FastAPI(
    title=settings.APP_NAME,
    description="Deterministic 90-day financial decision engine with Gemini multimodal evidence parsing.",
    version="1.0.0",
)

# Enable CORS for Stitch Frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Structured Exception Handlers


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Formats HTTP exceptions into the required Stitch error schema."""
    code_map = {
        400: "INVALID_REQUEST",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        500: "DECISION_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, "ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": exc.detail if isinstance(exc.detail, str) else "An error occurred.",
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Formats Pydantic validation errors into clean Stitch error schema without internal stack traces."""
    logger.warning(f"Request validation failed for {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Invalid request payload or missing required fields.",
            }
        },
    )


@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    """Catches all unhandled server exceptions safely without leaking stack traces or internal secrets."""
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "DECISION_UNAVAILABLE",
                "message": "We could not safely evaluate this request.",
            }
        },
    )


# Include Routers
app.include_router(health_router)
app.include_router(requests_router)
app.include_router(decision_router)


@app.on_event("startup")
def startup_event():
    logger.info(f"Starting {settings.APP_NAME} in {settings.ENVIRONMENT} mode.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
