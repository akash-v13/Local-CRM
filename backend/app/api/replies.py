"""AI reply drafting: templates, sample cases, the test lab, cost projections, drafts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.ai.drafter import DraftWriter
from app.ai.models import MODELS
from app.ai.setup import draft_writer_from
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.errors import AIUnavailableError
from app.schemas import (
    CostProjection,
    DraftRequest,
    MessageRead,
    ModelOption,
    ReplyTemplateRead,
    ReplyTemplateWrite,
    SampleCaseRead,
    SampleCaseWrite,
    TestRunCreate,
    TestRunEstimate,
    TestRunRead,
)
from app.services.replies import DraftService, ReplyTemplateService
from app.services.template_tests import SampleCaseService, TemplateTestService

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["ai drafting"])
models_router = APIRouter(tags=["ai drafting"])

DbSession = Annotated[Session, Depends(get_session)]


def get_draft_writer(settings: Annotated[Settings, Depends(get_settings)]) -> DraftWriter:
    """The model client. Tests replace this with a fake (no real API calls)."""
    writer = draft_writer_from(settings)
    if writer is None:
        raise AIUnavailableError(
            "AI drafting isn't set up: add ANTHROPIC_API_KEY to the backend environment "
            "(see docs/dev/local-setup.md)."
        )
    return writer


@models_router.get("/ai/models")
def list_models() -> list[ModelOption]:
    """Models a template can use, with list prices (USD per million tokens)."""
    return [
        ModelOption(
            id=m.id,
            label=m.label,
            summary=m.summary,
            input_per_mtok=m.input_per_mtok,
            output_per_mtok=m.output_per_mtok,
            supports_effort=m.supports_effort,
        )
        for m in MODELS.values()
    ]


# ----- templates ----------------------------------------------------------------------------


@router.get("/reply-templates")
def list_templates(tenant_id: uuid.UUID, session: DbSession) -> list[ReplyTemplateRead]:
    """All templates, in the order they're checked (priority, then age)."""
    service = ReplyTemplateService(session)
    return [service.to_read(t) for t in service.list_templates(tenant_id)]


@router.post("/reply-templates", status_code=status.HTTP_201_CREATED)
def create_template(
    tenant_id: uuid.UUID,
    body: ReplyTemplateWrite,
    session: DbSession,
    actor_id: str | None = None,
) -> ReplyTemplateRead:
    service = ReplyTemplateService(session)
    return service.to_read(service.create(tenant_id, body, actor_id))


@router.get("/reply-templates/{template_id}")
def get_template(
    tenant_id: uuid.UUID, template_id: uuid.UUID, session: DbSession
) -> ReplyTemplateRead:
    service = ReplyTemplateService(session)
    return service.to_read(service.get(tenant_id, template_id))


@router.put("/reply-templates/{template_id}")
def update_template(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    body: ReplyTemplateWrite,
    session: DbSession,
    actor_id: str | None = None,
) -> ReplyTemplateRead:
    """Changing the content (model, instructions, rules, checks) creates a new version."""
    service = ReplyTemplateService(session)
    return service.to_read(service.update(tenant_id, template_id, body, actor_id))


@router.get("/reply-templates/{template_id}/projection")
def cost_projection(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    session: DbSession,
    monthly_volume: Annotated[int, Query(ge=1, le=100_000_000)] = 10_000,
) -> CostProjection:
    """Cost per reply and per month on each model (measured where possible)."""
    return ReplyTemplateService(session).projection(tenant_id, template_id, monthly_volume)


# ----- sample cases -------------------------------------------------------------------------


@router.get("/sample-cases")
def list_samples(tenant_id: uuid.UUID, session: DbSession) -> list[SampleCaseRead]:
    return [
        SampleCaseRead.model_validate(s) for s in SampleCaseService(session).list_samples(tenant_id)
    ]


@router.post("/sample-cases", status_code=status.HTTP_201_CREATED)
def create_sample(
    tenant_id: uuid.UUID, body: SampleCaseWrite, session: DbSession
) -> SampleCaseRead:
    return SampleCaseRead.model_validate(SampleCaseService(session).save(tenant_id, body))


@router.put("/sample-cases/{sample_id}")
def update_sample(
    tenant_id: uuid.UUID, sample_id: uuid.UUID, body: SampleCaseWrite, session: DbSession
) -> SampleCaseRead:
    return SampleCaseRead.model_validate(
        SampleCaseService(session).save(tenant_id, body, sample_id)
    )


# ----- test lab -----------------------------------------------------------------------------


@router.post("/template-tests/estimate")
def estimate_test(tenant_id: uuid.UUID, body: TestRunCreate, session: DbSession) -> TestRunEstimate:
    """What a test run would cost, before running it. Free (no model calls)."""
    return TemplateTestService(session).estimate(tenant_id, body)


@router.post("/template-tests", status_code=status.HTTP_201_CREATED)
def start_test(
    tenant_id: uuid.UUID,
    body: TestRunCreate,
    session: DbSession,
    _writer: Annotated[DraftWriter, Depends(get_draft_writer)],  # fails fast if AI isn't set up
) -> TestRunRead:
    """Queue a test run (the worker drafts the replies; poll GET for progress)."""
    service = TemplateTestService(session)
    return service.to_read(service.create(tenant_id, body))


@router.get("/template-tests")
def recent_tests(
    tenant_id: uuid.UUID, session: DbSession, template_id: uuid.UUID | None = None
) -> list[TestRunRead]:
    service = TemplateTestService(session)
    return [service.to_read(r) for r in service.recent(tenant_id, template_id)]


@router.get("/template-tests/{run_id}")
def get_test(tenant_id: uuid.UUID, run_id: uuid.UUID, session: DbSession) -> TestRunRead:
    service = TemplateTestService(session)
    return service.to_read(service.get(tenant_id, run_id))


# ----- drafts on cases ----------------------------------------------------------------------


@router.post("/cases/{case_number}/drafts", status_code=status.HTTP_201_CREATED)
def draft_reply(
    tenant_id: uuid.UUID,
    case_number: int,
    body: DraftRequest,
    session: DbSession,
    writer: Annotated[DraftWriter, Depends(get_draft_writer)],
) -> MessageRead:
    """Draft a reply with AI, using the reply template that matches the case.

    The draft is saved on the case (visible to agents only) and never sent
    automatically: an agent reviews, edits and sends it.
    """
    return MessageRead.model_validate(
        DraftService(session).draft_for_case(tenant_id, case_number, writer, body.actor_id)
    )
