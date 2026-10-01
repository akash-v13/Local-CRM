"""AI reply drafting: prompt templates, sample cases, the test lab, cost projections, drafts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.ai.drafter import DraftWriter
from app.ai.engine import Checks, TemplateFile, parse_file, platform_source, to_file
from app.ai.models import MODELS
from app.ai.setup import draft_writer_from
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.errors import AIUnavailableError, NotFoundError
from app.repositories import CaseRepository, MessageRepository
from app.schemas import (
    CostProjection,
    CoverageRow,
    DraftRequest,
    MessageRead,
    ModelOption,
    PromptPreview,
    PromptPreviewRequest,
    PromptTemplateRead,
    PromptTemplateWrite,
    SampleCaseRead,
    SampleCaseWrite,
    TemplateImport,
    TemplateVariable,
    TestRunCreate,
    TestRunEstimate,
    TestRunRead,
)
from app.services.replies import (
    VARIABLE_REFERENCE,
    DraftService,
    PromptTemplateService,
    draft_input_from_case,
    draft_input_from_sample,
)
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


# ----- prompt templates ---------------------------------------------------------------------
# Names contain a slash (queue/…, category/…), hence the {name:path} parameters.
# Fixed routes are declared first so they aren't captured by {name:path}.


def get_template_service(session: DbSession) -> PromptTemplateService:
    return PromptTemplateService(session)


Templates = Annotated[PromptTemplateService, Depends(get_template_service)]


@router.get("/prompt-templates")
def list_templates(tenant_id: uuid.UUID, service: Templates) -> list[PromptTemplateRead]:
    """All of the business's templates (the starter pack is added automatically)."""
    return [service.to_read(t) for t in service.list_templates(tenant_id)]


@router.get("/prompt-templates/variables")
def template_variables() -> list[TemplateVariable]:
    """What templates can use. Personal data is masked before rendering."""
    return VARIABLE_REFERENCE


@router.get("/prompt-templates/coverage")
def template_coverage(tenant_id: uuid.UUID, service: Templates) -> list[CoverageRow]:
    """Which persona each queue uses and which template each category uses."""
    return service.coverage(tenant_id)


@router.get("/prompt-templates/platform", response_class=PlainTextResponse)
def platform_rules() -> str:
    """The locked platform guardrails every prompt starts with (read-only)."""
    return platform_source("guardrails.jinja")


@router.post("/prompt-templates/preview")
def preview_prompt(
    tenant_id: uuid.UUID, body: PromptPreviewRequest, session: DbSession, service: Templates
) -> PromptPreview:
    """The exact prompt a draft would use for a case or sample, layer by layer.
    Optionally with an unsaved edit. Free: no model call."""
    if body.case_number is not None:
        case = CaseRepository(session).get_by_number(tenant_id, body.case_number)
        if case is None:
            raise NotFoundError(f"Case {body.case_number} not found.")
        draft_input = draft_input_from_case(
            case, MessageRepository(session).list_for_case(tenant_id, case.id)
        )
    else:
        assert body.sample_id is not None
        draft_input = draft_input_from_sample(
            SampleCaseService(session).get(tenant_id, body.sample_id)
        )
    return service.preview(tenant_id, draft_input, body.override)


@router.post("/prompt-templates/import", status_code=status.HTTP_201_CREATED)
def import_template(
    tenant_id: uuid.UUID, body: TemplateImport, service: Templates, actor_id: str | None = None
) -> PromptTemplateRead:
    """Save a .jinja file's content (header with description/checks + body) as a template."""
    parsed = parse_file(body.content)
    data = PromptTemplateWrite(
        source=parsed.source,
        description=parsed.description,
        max_words=parsed.checks.max_words,
        must_include=parsed.checks.must_include,
        must_not_include=parsed.checks.must_not_include,
    )
    return service.to_read(service.save(tenant_id, body.name, data, actor_id))


@router.get("/prompt-templates/{name:path}/download", response_class=PlainTextResponse)
def download_template(tenant_id: uuid.UUID, name: str, service: Templates) -> PlainTextResponse:
    """The template as a .jinja file, header included (description and checks)."""
    template = service.get(tenant_id, name)
    v = service.current(template)
    content = to_file(
        TemplateFile(
            source=v.source,
            description=template.description,
            checks=Checks(v.max_words, list(v.must_include), list(v.must_not_include)),
        )
    )
    filename = name.replace("/", "__")
    return PlainTextResponse(
        content, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/prompt-templates/{name:path}/projection")
def cost_projection(
    tenant_id: uuid.UUID,
    name: str,
    service: Templates,
    monthly_volume: Annotated[int, Query(ge=1, le=100_000_000)] = 10_000,
) -> CostProjection:
    """Cost per reply and per month on each model for drafts using this template."""
    return service.projection(tenant_id, name, monthly_volume)


@router.get("/prompt-templates/{name:path}")
def get_template(tenant_id: uuid.UUID, name: str, service: Templates) -> PromptTemplateRead:
    return service.to_read(service.get(tenant_id, name))


@router.put("/prompt-templates/{name:path}")
def save_template(
    tenant_id: uuid.UUID,
    name: str,
    body: PromptTemplateWrite,
    service: Templates,
    actor_id: str | None = None,
) -> PromptTemplateRead:
    """Create the template, or save a new version if the source or checks changed.
    Rejected with 409 if the Jinja doesn't validate."""
    return service.to_read(service.save(tenant_id, name, body, actor_id))


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
    tenant_id: uuid.UUID, session: DbSession, template_name: str | None = None
) -> list[TestRunRead]:
    service = TemplateTestService(session)
    return [service.to_read(r) for r in service.recent(tenant_id, template_name)]


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
    """Draft a reply with AI, using the case's baseline, queue persona and case-type templates.

    The draft is saved on the case (visible to agents only) and never sent
    automatically: an agent reviews, edits and sends it.
    """
    return MessageRead.model_validate(
        DraftService(session).draft_for_case(tenant_id, case_number, writer, body.actor_id)
    )
