from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    """Readiness: the database is reachable."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
