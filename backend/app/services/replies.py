"""Reply templates, AI drafts on cases, and cost projections.

The drafting pipeline (also used by the template test lab):

    case/sample ──► DraftInput ──► mask personal data ──► prompt
        ──► Claude (structured output) ──► unmask ──► checks + warnings ──► DraftInfo
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.checks import run_checks
from app.ai.drafter import DraftError, DraftWriter
from app.ai.models import MODELS, TYPICAL_OUTPUT_TOKENS, Usage, cost_usd, estimate_tokens
from app.ai.pii import Masker, leftover_placeholders, unexpected_pii, unmask
from app.ai.prompts import DraftInput, TemplateSpec, build_system, build_user
from app.domain.errors import AIDisabledError, AIDraftFailedError, ConflictError, NotFoundError
from app.domain.lifecycle import CaseStatus
from app.domain.routing import evaluate_criteria
from app.models import (
    Case,
    CaseEvent,
    Message,
    ReplyTemplate,
    ReplyTemplateVersion,
    SampleCase,
    TemplateTestRun,
    Tenant,
)
from app.models.base import utcnow
from app.repositories import CaseRepository, MessageRepository, TenantRepository
from app.schemas import (
    CheckResultRead,
    CostProjection,
    CostProjectionRow,
    DraftInfo,
    MatchCriteria,
    ReplyTemplateRead,
    ReplyTemplateWrite,
    TemplateContent,
    TemplateVersionRead,
)
from app.services.routing import case_context, enrichment_data

DEFAULT_TEMPLATE_NAME = "Default reply"
DEFAULT_TEMPLATE = TemplateContent(
    model="claude-sonnet-5",
    effort="low",
    instructions=(
        "Write a short, warm, professional reply. Acknowledge the customer's concern in your own "
        "words, explain what the facts show and what happens next, and close politely. "
        "Keep it to 2-4 short paragraphs."
    ),
    max_words=180,
)

# Typical size of the per-case part of a prompt, for estimates before anything has run.
TYPICAL_CASE_PROMPT_TOKENS = 700


# ----- inputs -----------------------------------------------------------------------------


def draft_input_from_case(case: Case, messages: Sequence[Message]) -> DraftInput:
    """Only customer-visible messages go to the model (no internal notes, no earlier drafts)."""
    thread: list[tuple[str, str]] = []
    for m in messages:
        if m.visibility != "public":
            continue
        thread.append(("customer" if m.direction == "inbound" else "agent", m.body))
    names = {
        key: str(result.get("connectorName") or key)
        for key, result in case.enrichment.items()
        if isinstance(result, dict)
    }
    return DraftInput(
        reference=f"Case {case.case_number}",
        channel=case.channel,
        category=case.category.get("effective"),
        queue_name=case.queue.name if case.queue else None,
        customer_name=case.customer.display_name,
        customer_email=case.customer.email,
        customer_tier=case.customer.tier,
        attributes=dict(case.attributes),
        enrichment={names.get(k, k): v for k, v in enrichment_data(case).items()},
        thread=thread,
    )


def draft_input_from_sample(sample: SampleCase) -> DraftInput:
    return DraftInput(
        reference=f"Sample: {sample.name}",
        channel=sample.channel,
        category=dict(sample.category) or None,
        queue_name=sample.queue_name,
        customer_name=sample.customer_name,
        customer_email=None,
        customer_tier=sample.customer_tier,
        attributes={},
        enrichment={"Case data": dict(sample.facts)} if sample.facts else {},
        thread=[("customer", sample.message)],
    )


# ----- the pipeline -------------------------------------------------------------------------


def generate_draft(
    writer: DraftWriter,
    *,
    business_name: str,
    template_name: str,
    template_id: uuid.UUID | None,
    template_version: int | None,
    content: TemplateContent,
    draft_input: DraftInput,
) -> DraftInfo:
    """Mask → prompt → model → unmask → checks. Raises DraftError on failure."""
    masker = Masker(draft_input.customer_name, draft_input.customer_email)
    spec = TemplateSpec(template_name, content.instructions, content.rules, content.example_reply)
    system = build_system(business_name, spec)
    user = build_user(draft_input, masker)

    result = writer.write(model=content.model, effort=content.effort, system=system, user=user)
    reply = unmask(result.output.reply, masker.mapping).strip()

    warnings: list[str] = []
    leftovers = leftover_placeholders(reply)
    if leftovers:
        warnings.append(f"Fill in before sending: {', '.join(leftovers)}")
    sources = [text for _, text in draft_input.thread] + [
        str(draft_input.customer_email or ""),
        str(draft_input.attributes),
        str(draft_input.enrichment),
    ]
    for item in unexpected_pii(reply, sources):
        warnings.append(f"The draft contains a {item} that isn't in the case. Check it.")

    checks = run_checks(
        reply,
        max_words=content.max_words,
        must_include=content.must_include,
        must_not_include=content.must_not_include,
    )
    return DraftInfo(
        model=result.model,
        served_by=result.served_by,
        template_id=template_id,
        template_name=template_name,
        template_version=template_version,
        reply=reply,
        facts_used=result.output.facts_used,
        needs_attention=result.output.needs_human_attention,
        attention_reason=result.output.attention_reason,
        checks=[CheckResultRead(name=c.name, passed=c.passed, detail=c.detail) for c in checks],
        warnings=warnings,
        input_tokens=result.usage.input_tokens + result.usage.cache_write_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_tokens,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )


def estimate_cost(
    business_name: str, name: str, content: TemplateContent, draft_input: DraftInput, model: str
) -> float:
    """Planning estimate for one draft (no caching assumed, ~4 chars/token)."""
    spec = TemplateSpec(name, content.instructions, content.rules, content.example_reply)
    prompt = build_system(business_name, spec) + build_user(draft_input, Masker(None, None))
    output = int(content.max_words * 1.5) if content.max_words else TYPICAL_OUTPUT_TOKENS
    usage = Usage(input_tokens=estimate_tokens(prompt), output_tokens=output)
    return cost_usd(model, usage)


# ----- templates ----------------------------------------------------------------------------


def _version_read(v: ReplyTemplateVersion) -> TemplateVersionRead:
    return TemplateVersionRead.model_validate(v)


def content_of(v: ReplyTemplateVersion) -> TemplateContent:
    return TemplateContent.model_validate({f: getattr(v, f) for f in TemplateContent.model_fields})


@dataclass
class SelectedTemplate:
    template: ReplyTemplate
    version: ReplyTemplateVersion


class ReplyTemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)

    def _require_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def versions(self, template_id: uuid.UUID) -> list[ReplyTemplateVersion]:
        stmt = (
            select(ReplyTemplateVersion)
            .where(ReplyTemplateVersion.template_id == template_id)
            .order_by(ReplyTemplateVersion.version.desc())
        )
        return list(self.session.scalars(stmt).all())

    def to_read(self, template: ReplyTemplate) -> ReplyTemplateRead:
        versions = self.versions(template.id)
        current = next(v for v in versions if v.version == template.current_version)
        return ReplyTemplateRead(
            id=template.id,
            name=template.name,
            description=template.description,
            priority=template.priority,
            is_active=template.is_active,
            match_criteria=MatchCriteria.model_validate(dict(template.match_criteria)),
            current_version=template.current_version,
            current=_version_read(current),
            versions=[_version_read(v) for v in versions],
            created_at=template.created_at,
            updated_at=template.updated_at,
        )

    def list_templates(
        self, tenant_id: uuid.UUID, active_only: bool = False
    ) -> Sequence[ReplyTemplate]:
        self._require_tenant(tenant_id)
        stmt = select(ReplyTemplate).where(ReplyTemplate.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(ReplyTemplate.is_active.is_(True))
        return self.session.scalars(
            stmt.order_by(ReplyTemplate.priority, ReplyTemplate.created_at)
        ).all()

    def get(self, tenant_id: uuid.UUID, template_id: uuid.UUID) -> ReplyTemplate:
        stmt = select(ReplyTemplate).where(
            ReplyTemplate.tenant_id == tenant_id, ReplyTemplate.id == template_id
        )
        template = self.session.scalars(stmt).one_or_none()
        if template is None:
            raise NotFoundError(f"Reply template {template_id} not found.")
        return template

    def create(
        self, tenant_id: uuid.UUID, data: ReplyTemplateWrite, actor_id: str | None = None
    ) -> ReplyTemplate:
        self._require_tenant(tenant_id)
        template = ReplyTemplate(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            priority=data.priority,
            is_active=data.is_active,
            match_criteria=data.match_criteria.model_dump(),
            current_version=1,
        )
        self.session.add(template)
        try:
            self.session.flush()  # assigns template.id; a duplicate name fails here
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(f"A reply template named '{data.name}' already exists.") from exc
        self._add_version(template, 1, data, actor_id)
        self._commit(data.name)
        return template

    def update(
        self,
        tenant_id: uuid.UUID,
        template_id: uuid.UUID,
        data: ReplyTemplateWrite,
        actor_id: str | None = None,
    ) -> ReplyTemplate:
        """Settings change in place; content changes create a new version (old ones are kept)."""
        template = self.get(tenant_id, template_id)
        template.name = data.name
        template.description = data.description
        template.priority = data.priority
        template.is_active = data.is_active
        template.match_criteria = data.match_criteria.model_dump()
        current = next(
            v for v in self.versions(template.id) if v.version == template.current_version
        )
        new_content = TemplateContent.model_validate(
            data.model_dump(include=set(TemplateContent.model_fields))
        )
        if new_content != content_of(current):
            template.current_version += 1
            self._add_version(template, template.current_version, data, actor_id)
        template.updated_at = utcnow()
        self._commit(data.name)
        return template

    def _add_version(
        self, template: ReplyTemplate, version: int, data: TemplateContent, actor_id: str | None
    ) -> None:
        fields = data.model_dump(include=set(TemplateContent.model_fields))
        self.session.add(
            ReplyTemplateVersion(
                template_id=template.id, version=version, created_by=actor_id, **fields
            )
        )

    def _commit(self, name: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if "name" in str(exc.orig):
                raise ConflictError(f"A reply template named '{name}' already exists.") from exc
            raise

    def create_default(self, tenant_id: uuid.UUID) -> None:
        """The catch-all template every new tenant starts with (not committed here)."""
        template = ReplyTemplate(
            tenant_id=tenant_id,
            name=DEFAULT_TEMPLATE_NAME,
            description="Used when no other template matches.",
            priority=1000,
            is_active=True,
            match_criteria={"match": "all", "conditions": []},
            current_version=1,
        )
        self.session.add(template)
        self.session.flush()
        self._add_version(template, 1, DEFAULT_TEMPLATE, "system")

    def select_for(self, case: Case, customer_texts: list[str]) -> SelectedTemplate:
        """First active template (by priority) whose criteria match the case."""
        context = case_context(case, customer_texts)
        for template in self.list_templates(case.tenant_id, active_only=True):
            matched, _ = evaluate_criteria(dict(template.match_criteria), context)
            if matched:
                version = next(
                    v for v in self.versions(template.id) if v.version == template.current_version
                )
                return SelectedTemplate(template, version)
        raise AIDisabledError(
            "No active reply template matches this case. Add one in Operations → Reply templates."
        )

    # ----- cost projection ------------------------------------------------------------------

    def projection(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID, monthly_volume: int
    ) -> CostProjection:
        """Cost per reply and per month for each model.

        "measured" uses real token usage from this template's drafts and test
        runs (so it includes prompt-caching savings); "estimated" is used for
        models with no history yet.
        """
        tenant = self._require_tenant(tenant_id)
        template = self.get(tenant_id, template_id)
        current = content_of(
            next(v for v in self.versions(template.id) if v.version == template.current_version)
        )

        samples: dict[str, list[DraftInfo]] = {m: [] for m in MODELS}
        for info in self._history(tenant_id, template_id):
            if info.served_by in samples:
                samples[info.served_by].append(info)

        spec = TemplateSpec(
            template.name, current.instructions, current.rules, current.example_reply
        )
        system_tokens = estimate_tokens(build_system(tenant.name, spec))
        est_input = system_tokens + TYPICAL_CASE_PROMPT_TOKENS
        est_output = int(current.max_words * 1.5) if current.max_words else TYPICAL_OUTPUT_TOKENS

        rows: list[CostProjectionRow] = []
        for model_id, model_info in MODELS.items():
            history = samples[model_id]
            if history:
                per_reply = mean(d.cost_usd for d in history)
                avg_in = mean(d.input_tokens + d.cache_read_tokens for d in history)
                avg_out = mean(d.output_tokens for d in history)
                source: Any = "measured"
            else:
                per_reply = cost_usd(
                    model_id, Usage(input_tokens=est_input, output_tokens=est_output)
                )
                avg_in, avg_out, source = est_input, est_output, "estimated"
            rows.append(
                CostProjectionRow(
                    model=model_id,
                    label=model_info.label,
                    source=source,
                    sample_size=len(history),
                    avg_input_tokens=round(avg_in, 1),
                    avg_output_tokens=round(avg_out, 1),
                    cost_per_reply_usd=per_reply,
                    cost_per_1000_usd=per_reply * 1000,
                    monthly_cost_usd=per_reply * monthly_volume,
                )
            )
        return CostProjection(
            monthly_volume=monthly_volume,
            rows=rows,
            notes=[
                "Measured costs come from real drafts and test runs of this template, "
                "including prompt-caching savings.",
                "Estimates assume ~4 characters per token and no caching; run a test to "
                "replace them with measurements.",
                f"Template currently set to {MODELS[current.model].label}. "
                "Effort and reply length change costs.",
                "Drafting that doesn't need an instant answer (e.g. overnight backlogs) can "
                "use the Message Batches API at 50% of these prices.",
            ],
        )

    def _history(self, tenant_id: uuid.UUID, template_id: uuid.UUID) -> list[DraftInfo]:
        """Recent drafts (on cases and in test runs) produced by this template."""
        infos: list[DraftInfo] = []
        drafts = self.session.scalars(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.author_type == "ai")
            .order_by(Message.created_at.desc())
            .limit(500)
        ).all()
        for m in drafts:
            if m.ai.get("template_id") == str(template_id):
                infos.append(DraftInfo.model_validate(m.ai))
        runs = self.session.scalars(
            select(TemplateTestRun)
            .where(
                TemplateTestRun.tenant_id == tenant_id, TemplateTestRun.template_id == template_id
            )
            .order_by(TemplateTestRun.created_at.desc())
            .limit(20)
        ).all()
        for run in runs:
            for r in run.results:
                if r.get("ok") and r.get("draft"):
                    infos.append(DraftInfo.model_validate(r["draft"]))
        return infos


# ----- drafts on cases ----------------------------------------------------------------------


class DraftService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)
        self.templates = ReplyTemplateService(session)

    def draft_for_case(
        self, tenant_id: uuid.UUID, case_number: int, writer: DraftWriter, actor_id: str | None
    ) -> Message:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        if CaseStatus(case.status) is CaseStatus.CLOSED:
            raise AIDisabledError("This case is closed.")
        queue = case.queue
        if queue is None or not queue.settings.get("gen_ai_allowed"):
            where = f"the '{queue.name}' queue" if queue else "cases without a queue"
            raise AIDisabledError(
                f"AI drafting is turned off for {where}. A manager can turn it on in "
                'Operations → Queues & routing ("Allow AI to draft replies").'
            )

        tenant = self.tenants.get(tenant_id)
        assert tenant is not None
        messages = self.messages.list_for_case(tenant_id, case.id)
        customer_texts = [m.body for m in messages if m.author_type == "customer"]
        selected = self.templates.select_for(case, customer_texts)
        draft_input = draft_input_from_case(case, messages)
        template_name, template_id = selected.template.name, selected.template.id
        version, content = selected.version.version, content_of(selected.version)
        case_id = case.id
        # End the read transaction before calling the model (no DB connection held while waiting).
        self.session.commit()

        try:
            info = generate_draft(
                writer,
                business_name=tenant.name,
                template_name=template_name,
                template_id=template_id,
                template_version=version,
                content=content,
                draft_input=draft_input,
            )
        except DraftError as exc:
            raise AIDraftFailedError(str(exc)) from exc

        message = Message(
            tenant_id=tenant_id,
            case_id=case_id,
            direction="internal",
            channel="draft",
            author_type="ai",
            author_id=info.served_by,
            visibility="draft",
            body=info.reply,
            ai=info.model_dump(mode="json"),
        )
        self.messages.add(message)
        self.session.flush()
        self.session.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case_id,
                event_type="ai.draft_created",
                actor_type="human" if actor_id else "system",
                actor_id=actor_id,
                data={
                    "messageId": str(message.id),
                    "template": template_name,
                    "templateVersion": version,
                    "model": info.served_by,
                    "costUsd": round(info.cost_usd, 6),
                    "needsAttention": info.needs_attention,
                },
            )
        )
        self.session.commit()
        return message
