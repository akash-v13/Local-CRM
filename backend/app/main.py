"""FastAPI application entry point.

Run locally:  uv run uvicorn app.main:app --reload
Interactive API docs: http://localhost:8000/docs
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import cases, connectors, credentials, health, queues, replies, reports, tenants
from app.domain.errors import (
    AIDisabledError,
    AIDraftFailedError,
    AIUnavailableError,
    CaseClosedError,
    ConflictError,
    DomainError,
    InvalidTransitionError,
    NotFoundError,
    RoutingError,
)

app = FastAPI(
    title="Resolution Platform API",
    version="0.1.0",
    description="Case intake and lifecycle for the customer care resolution platform.",
)

app.include_router(health.router)
app.include_router(tenants.router)
app.include_router(cases.router)
app.include_router(queues.router)
app.include_router(queues.routing_router)
app.include_router(reports.router)
app.include_router(connectors.router)
app.include_router(credentials.router)
app.include_router(replies.router)
app.include_router(replies.models_router)


# Map domain errors (raised by services) to HTTP responses in one place.
# To add a new error: define it in app/domain/errors.py and add it here.
ERROR_STATUS_CODES: dict[type[DomainError], int] = {
    NotFoundError: 404,
    InvalidTransitionError: 409,
    CaseClosedError: 409,
    RoutingError: 409,
    AIDisabledError: 409,
    AIUnavailableError: 503,
    AIDraftFailedError: 502,
    ConflictError: 409,
}


@app.exception_handler(DomainError)
def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    code = next((c for cls, c in ERROR_STATUS_CODES.items() if isinstance(exc, cls)), 400)
    return JSONResponse(status_code=code, content={"detail": str(exc)})
