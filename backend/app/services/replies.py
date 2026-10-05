"""Prompt templates, AI drafts on cases, and cost projections.

The drafting pipeline (also used by the template test lab and preview):

    case/sample ──► DraftInput ──► masked context ──► layered Jinja templates
        (baseline + queue persona + case type) ──► Claude (structured output)
        ──► unmask ──► checks + warnings ──► DraftInfo
"""

import uuid
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.checks import run_checks, unsupported_commitments
from app.ai.context import DraftInput, build_context
from app.ai.drafter import DraftError, DraftWriter
from app.ai.engine import (
    BuiltPrompt,
    Checks,
    StoredTemplate,
    TemplateError,
    build_prompt,
    category_names,
    default_files,
    is_valid_name,
    kind_of,
    persona_names,
    validate,
)
from app.ai.models import MODELS, TYPICAL_OUTPUT_TOKENS, Effort, Usage, cost_usd, estimate_tokens
from app.ai.pii import Masker, leftover_placeholders, unexpected_pii, unmask
from app.domain.errors import AIDisabledError, AIDraftFailedError, ConflictError, NotFoundError
from app.domain.lifecycle import CaseStatus
from app.domain.taxonomy import DEFAULT_TAXONOMY
from app.models import (
    Case,
    CaseEvent,
    Message,
    PromptTemplate,
    PromptTemplateVersion,
    Queue,
    SampleCase,
    TemplateTestRun,
    Tenant,
)
from app.models.base import utcnow
from app.repositories import CaseRepository, MessageRepository, QueueRepository, TenantRepository
from app.schemas import (
    CheckResultRead,
    CostProjection,
    CostProjectionRow,
    CoverageRow,
    DraftInfo,
    LayerRead,
    PromptPreview,
    PromptTemplateRead,
    PromptTemplateVersionRead,
    PromptTemplateWrite,
    QueueSettings,
    TemplateChecks,
    TemplateOverride,
    TemplateRef,
    TemplateVariable,
)
from app.services.routing import enrichment_data

# `created_by` of versions written by the starter pack (not a person).
STARTER = "starter pack"

# Typical size of the per-case user message, for estimates before anything has run.
TYPICAL_CASE_PROMPT_TOKENS = 700

VARIABLE_REFERENCE = [
    TemplateVariable(path="business.name", description="Your business name", example="Acme Store"),
    TemplateVariable(path="case.type", description="Case type", example="Complaint"),
    TemplateVariable(path="case.category", description="Category", example="Delivery"),
    TemplateVariable(path="case.subcategory", description="Subcategory", example="Late delivery"),
    TemplateVariable(path="case.queue", description="Queue name", example="General"),
    TemplateVariable(path="case.channel", description="How the case arrived", example="webform"),
    TemplateVariable(path="case.number", description="Case number", example="1790812345678901"),
    TemplateVariable(
        path="case.attributes",
        description="Custom fields from intake (dict)",
        example="case.attributes.orderNumber",
    ),
    TemplateVariable(
        path="customer.name",
        description="Name placeholder, or none if unknown",
        example="[CUSTOMER_NAME]",
    ),
    TemplateVariable(
        path="customer.first_name",
        description="First-name placeholder, or none",
        example="[CUSTOMER_FIRST_NAME]",
    ),
    TemplateVariable(
        path="customer.tier", description="Loyalty / value tier, or none", example="Gold"
    ),
    TemplateVariable(
        path="enrichment",
        description="Connector data: enrichment.<connector key>.<field>. Guard with `is defined`.",
        example="enrichment.shop_orders.daysLate",
    ),
    TemplateVariable(
        path="decisions.compensation",
        description="Decided compensation, or none",
        example="none yet",
    ),
    TemplateVariable(path="latest_message", description="The customer's latest message (masked)"),
    TemplateVariable(path="thread", description="Customer-visible messages: list of {from, text}"),
]


# ----- inputs -----------------------------------------------------------------------------


def approved_compensation(case: Case) -> str | None:
    """What the AI may tell the customer: only an approved decision (never a pending one)."""
    decision = case.decisions.get("compensation") or {}
    return decision.get("label") if decision.get("status") == "approved" else None


def draft_input_from_case(case: Case, messages: Sequence[Message]) -> DraftInput:
    """Only customer-visible messages go to the model (no internal notes, no earlier drafts)."""
    thread = [
        ("customer" if m.direction == "inbound" else "agent", m.body)
        for m in messages
        if m.visibility == "public"
    ]
    labels = {
        key: str(result.get("connectorName") or key)
        for key, result in case.enrichment.items()
        if isinstance(result, dict)
    }
    return DraftInput(
        reference=f"Case {case.case_number}",
        case_number=case.case_number,
        channel=case.channel,
        category=case.category.get("effective"),
        queue_name=case.queue.name if case.queue else None,
        customer_name=case.customer.display_name,
        customer_email=case.customer.email,
        customer_tier=case.customer.tier,
        attributes=dict(case.attributes),
        enrichment=enrichment_data(case),
        enrichment_labels=labels,
        thread=thread,
        compensation=approved_compensation(case),
    )


def draft_input_from_sample(sample: SampleCase) -> DraftInput:
    return DraftInput(
        reference=f"Sample: {sample.name}",
        case_number=None,
        channel=sample.channel,
        category=dict(sample.category) or None,
        queue_name=sample.queue_name,
        customer_name=sample.customer_name,
        customer_email=None,
        customer_tier=sample.customer_tier,
        attributes={},
        enrichment={"case_data": dict(sample.facts)} if sample.facts else {},
        enrichment_labels={"case_data": "Case data"},
        thread=[("customer", sample.message)],
    )


# ----- the pipeline -------------------------------------------------------------------------


def prepare(
    templates: Mapping[str, StoredTemplate],
    business_name: str,
    draft_input: DraftInput,
    pinned: str | None = None,
) -> tuple[BuiltPrompt, Masker]:
    """Mask the input and render the layered prompt. Raises TemplateError."""
    masker = Masker(draft_input.customer_name, draft_input.customer_email)
    context = build_context(business_name, draft_input, masker)
    return build_prompt(templates, context, pinned), masker


class TemplateDraftError(DraftError):
    """The prompt couldn't be built: a template needs fixing (not a model failure)."""


def generate_draft(
    writer: DraftWriter,
    *,
    templates: Mapping[str, StoredTemplate],
    business_name: str,
    draft_input: DraftInput,
    model: str,
    effort: Effort,
    pinned: str | None = None,
) -> DraftInfo:
    """Prompt → model → unmask → checks. Raises DraftError (incl. template errors)."""
    try:
        prompt, masker = prepare(templates, business_name, draft_input, pinned)
    except TemplateError as exc:
        raise TemplateDraftError(f"Prompt template problem in {exc}") from exc

    result = writer.write(
        model=model,
        effort=effort,
        system=[prompt.system_platform, prompt.system_layers],
        user=prompt.user,
    )
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
    warnings += unsupported_commitments(
        reply,
        prompt.system_layers + "\n" + prompt.user,
        compensation=draft_input.compensation,
        flagged=result.output.needs_human_attention,
        customer_text=" ".join(text for who, text in draft_input.thread if who == "customer"),
    )

    checks = run_checks(
        reply,
        max_words=prompt.checks.max_words,
        must_include=prompt.checks.must_include,
        must_not_include=prompt.checks.must_not_include,
    )
    return DraftInfo(
        model=result.model,
        served_by=result.served_by,
        templates=[
            TemplateRef(layer=x.layer, name=x.name, version=x.version) for x in prompt.layers
        ],
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
    templates: Mapping[str, StoredTemplate],
    business_name: str,
    draft_input: DraftInput,
    model: str,
    pinned: str | None = None,
) -> float:
    """Planning estimate for one draft (no caching assumed, ~4 chars/token)."""
    try:
        prompt, _ = prepare(templates, business_name, draft_input, pinned)
        text = prompt.system_platform + prompt.system_layers + prompt.user
        limit = prompt.checks.max_words
    except TemplateError:
        text, limit = "", None
    output = int(limit * 1.5) if limit else TYPICAL_OUTPUT_TOKENS
    return cost_usd(model, Usage(input_tokens=estimate_tokens(text) or 1, output_tokens=output))


def _to_checks(source: TemplateChecks | PromptTemplateVersion) -> Checks:
    return Checks(
        max_words=source.max_words,
        must_include=list(source.must_include),
        must_not_include=list(source.must_not_include),
    )


def queue_ai_settings(queue: Queue | None) -> tuple[str, Effort]:
    settings = QueueSettings.model_validate(dict(queue.settings) if queue else {})
    return settings.ai_model, settings.ai_effort


# ----- templates ----------------------------------------------------------------------------


class PromptTemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.queues = QueueRepository(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def ensure_defaults(self, tenant_id: uuid.UUID, *, commit: bool = True) -> None:
        """Keep the tenant's starter templates current, never touching anyone's edits:
        - add any starter template the tenant doesn't have;
        - if a template is still exactly as the starter pack wrote it (current version
          created by "starter pack") and the starter has changed, add the new starter
          content as a new version. Edited templates are never changed.
        """
        templates = {
            t.name: t
            for t in self.session.scalars(
                select(PromptTemplate).where(PromptTemplate.tenant_id == tenant_id)
            ).all()
        }
        added = False
        for name, file in default_files().items():
            template = templates.get(name)
            if template is None:
                template = PromptTemplate(
                    tenant_id=tenant_id,
                    name=name,
                    kind=kind_of(name),
                    description=file.description,
                    current_version=0,
                )
                self.session.add(template)
                self.session.flush()
            else:
                current = self.current(template)
                unchanged = (
                    current.source == file.source
                    and current.max_words == file.checks.max_words
                    and list(current.must_include) == file.checks.must_include
                    and list(current.must_not_include) == file.checks.must_not_include
                )
                if current.created_by != STARTER or unchanged:
                    continue
            template.current_version += 1
            template.description = file.description
            template.updated_at = utcnow()
            self.session.add(
                PromptTemplateVersion(
                    template_id=template.id,
                    version=template.current_version,
                    source=file.source,
                    max_words=file.checks.max_words,
                    must_include=file.checks.must_include,
                    must_not_include=file.checks.must_not_include,
                    created_by=STARTER,
                )
            )
            added = True
        if added and commit:
            self.session.commit()

    def list_templates(self, tenant_id: uuid.UUID) -> Sequence[PromptTemplate]:
        self._tenant(tenant_id)
        self.ensure_defaults(tenant_id)
        stmt = select(PromptTemplate).where(PromptTemplate.tenant_id == tenant_id)
        return self.session.scalars(stmt.order_by(PromptTemplate.name)).all()

    def get(self, tenant_id: uuid.UUID, name: str) -> PromptTemplate:
        self.ensure_defaults(tenant_id)
        stmt = select(PromptTemplate).where(
            PromptTemplate.tenant_id == tenant_id, PromptTemplate.name == name
        )
        template = self.session.scalars(stmt).one_or_none()
        if template is None:
            raise NotFoundError(f"Template {name} not found.")
        return template

    def versions(self, template: PromptTemplate) -> list[PromptTemplateVersion]:
        stmt = (
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == template.id)
            .order_by(PromptTemplateVersion.version.desc())
        )
        return list(self.session.scalars(stmt).all())

    def current(self, template: PromptTemplate) -> PromptTemplateVersion:
        return next(v for v in self.versions(template) if v.version == template.current_version)

    def to_read(self, template: PromptTemplate) -> PromptTemplateRead:
        versions = self.versions(template)
        current = next(v for v in versions if v.version == template.current_version)
        default = default_files().get(template.name)
        return PromptTemplateRead(
            name=template.name,
            kind=template.kind,
            description=template.description,
            current_version=template.current_version,
            current=PromptTemplateVersionRead.model_validate(current),
            versions=[PromptTemplateVersionRead.model_validate(v) for v in versions],
            is_default_content=bool(
                default
                and default.source.strip() == current.source.strip()
                and default.checks
                == Checks(
                    current.max_words, list(current.must_include), list(current.must_not_include)
                )
            ),
            updated_at=template.updated_at,
        )

    def save(
        self, tenant_id: uuid.UUID, name: str, data: PromptTemplateWrite, actor_id: str | None
    ) -> PromptTemplate:
        """Create the template, or add a version if the source or checks changed."""
        self._tenant(tenant_id)
        if not is_valid_name(name):
            raise ConflictError(
                "Template names look like base.jinja, queue/<Queue>.jinja or "
                "category/<Type>_<Category>_<Subcategory>.jinja (letters, digits, _)."
            )
        problems = validate(data.source)
        if problems:
            raise ConflictError("The template can't be saved:\n" + "\n".join(problems))
        self.ensure_defaults(tenant_id, commit=False)

        stmt = select(PromptTemplate).where(
            PromptTemplate.tenant_id == tenant_id, PromptTemplate.name == name
        )
        template = self.session.scalars(stmt).one_or_none()
        if template is None:
            template = PromptTemplate(
                tenant_id=tenant_id, name=name, kind=kind_of(name), current_version=0
            )
            self.session.add(template)
            try:
                self.session.flush()
            except IntegrityError as exc:
                self.session.rollback()
                raise ConflictError(f"Template {name} already exists.") from exc
        else:
            current = self.current(template)
            unchanged = current.source.strip() == data.source.strip() and _to_checks(
                current
            ) == _to_checks(data)
            if unchanged:
                template.description = data.description
                self.session.commit()
                return template

        template.description = data.description
        template.current_version += 1
        self.session.add(
            PromptTemplateVersion(
                template_id=template.id,
                version=template.current_version,
                source=data.source.strip() + "\n",
                max_words=data.max_words,
                must_include=data.must_include,
                must_not_include=data.must_not_include,
                created_by=actor_id,
            )
        )
        template.updated_at = utcnow()
        self.session.commit()
        return template

    def store(
        self, tenant_id: uuid.UUID, override: TemplateOverride | None = None
    ) -> dict[str, StoredTemplate]:
        """Current version of every template, with an unsaved edit swapped in if given."""
        self.ensure_defaults(tenant_id)
        templates: dict[str, StoredTemplate] = {}
        for t in self.session.scalars(
            select(PromptTemplate).where(PromptTemplate.tenant_id == tenant_id)
        ).all():
            v = self.current(t)
            templates[t.name] = StoredTemplate(t.name, v.version, v.source, _to_checks(v))
        if override is not None:
            templates[override.name] = StoredTemplate(
                override.name, None, override.source, _to_checks(override)
            )
        return templates

    def preview(
        self, tenant_id: uuid.UUID, draft_input: DraftInput, override: TemplateOverride | None
    ) -> PromptPreview:
        """The exact prompt a draft would use, layer by layer. No model call."""
        tenant = self._tenant(tenant_id)
        queue = self._queue_named(tenant_id, draft_input.queue_name)
        model, effort = queue_ai_settings(queue)
        if override is not None:
            problems = validate(override.source)
            if problems:
                return PromptPreview(ok=False, error=f"{override.name}: " + " ".join(problems))
        try:
            prompt, _ = prepare(
                self.store(tenant_id, override),
                tenant.name,
                draft_input,
                pinned=override.name if override else None,
            )
        except TemplateError as exc:
            return PromptPreview(ok=False, error=str(exc))
        return PromptPreview(
            ok=True,
            system_platform=prompt.system_platform,
            layers=[
                LayerRead(layer=x.layer, name=x.name, version=x.version, text=x.text)
                for x in prompt.layers
            ],
            user=prompt.user,
            checks=TemplateChecks(
                max_words=prompt.checks.max_words,
                must_include=prompt.checks.must_include,
                must_not_include=prompt.checks.must_not_include,
            ),
            model=model,
            effort=effort,
        )

    def _queue_named(self, tenant_id: uuid.UUID, name: str | None) -> Queue | None:
        if not name:
            return None
        return next((q for q in self.queues.list(tenant_id) if q.name == name), None)

    def coverage(self, tenant_id: uuid.UUID) -> list[CoverageRow]:
        """For every queue and every taxonomy category: which template it uses now."""
        names = set(self.store(tenant_id))
        rows: list[CoverageRow] = []
        for queue in self.queues.list(tenant_id):
            chain = persona_names(queue.name)
            used = next(n for n in chain if n in names)
            rows.append(
                CoverageRow(
                    kind="persona",
                    label=queue.name,
                    template=used,
                    specific=used == chain[0],
                    expected_name=chain[0],
                )
            )
        for t in DEFAULT_TAXONOMY:
            for c in t["categories"]:
                for sub in c["subcategories"]:
                    chain = category_names(
                        {"type": t["name"], "category": c["name"], "subcategory": sub["name"]}
                    )
                    used = next(n for n in chain if n in names)
                    rows.append(
                        CoverageRow(
                            kind="category",
                            label=f"{t['name']} › {c['name']} › {sub['name']}",
                            template=used,
                            specific=used != chain[-1],
                            expected_name=chain[0],
                        )
                    )
        return rows

    # ----- cost projection ------------------------------------------------------------------

    def projection(self, tenant_id: uuid.UUID, name: str, monthly_volume: int) -> CostProjection:
        """Cost per reply and per month for each model, for drafts that use this template.

        "measured" uses real token usage from drafts and test runs that used this
        template (so it includes prompt-caching savings); "estimated" is used for
        models with no history yet.
        """
        template = self.get(tenant_id, name)
        current = self.current(template)

        samples: dict[str, list[DraftInfo]] = {m: [] for m in MODELS}
        for info in self._history(tenant_id, name):
            if info.served_by in samples:
                samples[info.served_by].append(info)

        # Estimate: this template plus the baseline and default persona, the platform
        # rules (~400 tokens) and a typical case.
        store = self.store(tenant_id)
        layer_text = "\n".join(
            store[n].source for n in (name, "base.jinja", "queue/_default.jinja") if n in store
        )
        est_input = estimate_tokens(layer_text) + 400 + TYPICAL_CASE_PROMPT_TOKENS
        est_output = int(current.max_words * 1.5) if current.max_words else TYPICAL_OUTPUT_TOKENS

        rows: list[CostProjectionRow] = []
        for model_id, model_info in MODELS.items():
            history = samples[model_id]
            source: Literal["measured", "estimated"]
            if history:
                per_reply = mean(d.cost_usd for d in history)
                avg_in = mean(d.input_tokens + d.cache_read_tokens for d in history)
                avg_out = mean(d.output_tokens for d in history)
                source = "measured"
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
                "Measured costs come from real drafts and test runs that used this template, "
                "including prompt-caching savings.",
                "Estimates assume ~4 characters per token and no caching; run a test to "
                "replace them with measurements.",
                "The model is set per queue (Operations → Queues → Handling). Effort and "
                "reply length change costs.",
                "Drafting that doesn't need an instant answer (e.g. overnight backlogs) can "
                "use the Message Batches API at 50% of these prices.",
            ],
        )

    def _history(self, tenant_id: uuid.UUID, name: str) -> list[DraftInfo]:
        """Recent drafts (on cases and in test runs) that used this template."""
        infos: list[DraftInfo] = []
        drafts = self.session.scalars(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.author_type == "ai")
            .order_by(Message.created_at.desc())
            .limit(500)
        ).all()
        runs = self.session.scalars(
            select(TemplateTestRun)
            .where(TemplateTestRun.tenant_id == tenant_id)
            .order_by(TemplateTestRun.created_at.desc())
            .limit(20)
        ).all()
        candidates: list[dict[str, Any]] = [dict(m.ai) for m in drafts]
        candidates += [
            r["draft"] for run in runs for r in run.results if r.get("ok") and r.get("draft")
        ]
        for raw in candidates:
            info = DraftInfo.model_validate(raw)
            if any(t.name == name for t in info.templates):
                infos.append(info)
        return infos


# ----- drafts on cases ----------------------------------------------------------------------


class DraftService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)
        self.templates = PromptTemplateService(session)

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
        model, effort = queue_ai_settings(queue)

        tenant = self.tenants.get(tenant_id)
        assert tenant is not None
        templates = self.templates.store(tenant_id)
        draft_input = draft_input_from_case(case, self.messages.list_for_case(tenant_id, case.id))
        case_id = case.id
        # End the read transaction before calling the model (no DB connection held while waiting).
        self.session.commit()

        try:
            info = generate_draft(
                writer,
                templates=templates,
                business_name=tenant.name,
                draft_input=draft_input,
                model=model,
                effort=effort,
            )
        except TemplateDraftError as exc:
            raise AIDisabledError(str(exc)) from exc
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
                    "templates": [f"{t.name} v{t.version}" for t in info.templates],
                    "model": info.served_by,
                    "costUsd": round(info.cost_usd, 6),
                    "needsAttention": info.needs_attention,
                },
            )
        )
        self.session.commit()
        return message
