"""Template test lab: sample cases, cost estimates, and test runs.

A test run drafts replies for every (model × input × repeat) with the
template *as currently edited* (saved or not), so a manager can compare
models on quality, consistency and cost before changing anything for real.

Runs execute on the worker (job kind "template_test"), several drafts in
parallel; results are saved as each one finishes so the UI shows progress.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.checks import consistency, word_count
from app.ai.drafter import DraftError, DraftWriter
from app.ai.models import MODELS
from app.ai.prompts import DraftInput
from app.domain.errors import ConflictError, NotFoundError
from app.models import Job, SampleCase, TemplateTestRun, Tenant
from app.repositories import CaseRepository, MessageRepository, TenantRepository
from app.schemas import (
    ModelSummary,
    ReplyTemplateWrite,
    SampleCaseWrite,
    TemplateContent,
    TestResult,
    TestRunCreate,
    TestRunEstimate,
    TestRunRead,
)
from app.services.replies import (
    draft_input_from_case,
    draft_input_from_sample,
    estimate_cost,
    generate_draft,
)

PARALLEL_DRAFTS = 4


class SampleCaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)

    def list_samples(self, tenant_id: uuid.UUID) -> Sequence[SampleCase]:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        stmt = select(SampleCase).where(SampleCase.tenant_id == tenant_id).order_by(SampleCase.name)
        return self.session.scalars(stmt).all()

    def get(self, tenant_id: uuid.UUID, sample_id: uuid.UUID) -> SampleCase:
        stmt = select(SampleCase).where(
            SampleCase.tenant_id == tenant_id, SampleCase.id == sample_id
        )
        sample = self.session.scalars(stmt).one_or_none()
        if sample is None:
            raise NotFoundError(f"Sample {sample_id} not found.")
        return sample

    def save(
        self, tenant_id: uuid.UUID, data: SampleCaseWrite, sample_id: uuid.UUID | None = None
    ) -> SampleCase:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        sample = self.get(tenant_id, sample_id) if sample_id else SampleCase(tenant_id=tenant_id)
        values = data.model_dump()
        values["category"] = values["category"] or {}
        for name, value in values.items():
            setattr(sample, name, value)
        if sample_id is None:
            self.session.add(sample)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(f"A sample named '{data.name}' already exists.") from exc
        return sample


def _content(template: ReplyTemplateWrite) -> TemplateContent:
    return TemplateContent.model_validate(
        template.model_dump(include=set(TemplateContent.model_fields))
    )


def summarize(results: list[TestResult], models: list[str]) -> list[ModelSummary]:
    """Per model: check pass rate, consistency across repeats, cost and speed."""
    summaries: list[ModelSummary] = []
    for model in models:
        rows = [r for r in results if r.model == model]
        drafts = [r.draft for r in rows if r.ok and r.draft]
        checks = [c for d in drafts for c in d.checks]
        by_input: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            if r.ok and r.draft:
                by_input[r.input_ref].append(r.draft.reply)
        scores = [s for s in (consistency(v) for v in by_input.values()) if s is not None]
        summaries.append(
            ModelSummary(
                model=model,
                label=MODELS[model].label,
                drafts=len(drafts),
                errors=sum(1 for r in rows if not r.ok),
                checks_passed_pct=(
                    100 * sum(c.passed for c in checks) / len(checks) if checks else None
                ),
                consistency=mean(scores) if scores else None,
                needs_attention=sum(1 for d in drafts if d.needs_attention),
                avg_words=mean(word_count(d.reply) for d in drafts) if drafts else None,
                avg_cost_usd=mean(d.cost_usd for d in drafts) if drafts else None,
                avg_latency_ms=mean(d.latency_ms for d in drafts) if drafts else None,
                total_cost_usd=sum(d.cost_usd for d in drafts),
            )
        )
    return summaries


class TemplateTestService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)
        self.samples = SampleCaseService(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def inputs(self, tenant_id: uuid.UUID, req: TestRunCreate) -> list[tuple[str, str, DraftInput]]:
        """(reference, label, input) for every sample and case in the request."""
        out: list[tuple[str, str, DraftInput]] = []
        for sample_id in req.sample_ids:
            sample = self.samples.get(tenant_id, sample_id)
            out.append((f"sample:{sample.id}", sample.name, draft_input_from_sample(sample)))
        for number in req.case_numbers:
            case = self.cases.get_by_number(tenant_id, number)
            if case is None:
                raise NotFoundError(f"Case {number} not found.")
            messages = self.messages.list_for_case(tenant_id, case.id)
            out.append((f"case:{number}", f"Case {number}", draft_input_from_case(case, messages)))
        return out

    def estimate(self, tenant_id: uuid.UUID, req: TestRunCreate) -> TestRunEstimate:
        tenant = self._tenant(tenant_id)
        content = _content(req.template)
        per_model: dict[str, float] = {}
        inputs = self.inputs(tenant_id, req)
        for model in req.models:
            per_model[model] = req.runs_per_input * sum(
                estimate_cost(tenant.name, req.template.name, content, inp, model)
                for _, _, inp in inputs
            )
        return TestRunEstimate(
            total_calls=len(inputs) * len(req.models) * req.runs_per_input,
            estimated_cost_usd=sum(per_model.values()),
            per_model=per_model,
        )

    def create(self, tenant_id: uuid.UUID, req: TestRunCreate) -> TemplateTestRun:
        estimate = self.estimate(tenant_id, req)
        run = TemplateTestRun(
            tenant_id=tenant_id,
            template_id=req.template_id,
            template_version=None,
            config=req.model_dump(mode="json"),
            status="pending",
            total_calls=estimate.total_calls,
            results=[],
            estimated_cost_usd=estimate.estimated_cost_usd,
            actual_cost_usd=0.0,
            created_by=req.actor_id,
        )
        self.session.add(run)
        self.session.flush()
        self.session.add(
            Job(tenant_id=tenant_id, kind="template_test", payload={"run_id": str(run.id)})
        )
        self.session.commit()
        return run

    def get(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> TemplateTestRun:
        stmt = select(TemplateTestRun).where(
            TemplateTestRun.tenant_id == tenant_id, TemplateTestRun.id == run_id
        )
        run = self.session.scalars(stmt).one_or_none()
        if run is None:
            raise NotFoundError(f"Test run {run_id} not found.")
        return run

    def recent(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID | None
    ) -> Sequence[TemplateTestRun]:
        stmt = select(TemplateTestRun).where(TemplateTestRun.tenant_id == tenant_id)
        if template_id:
            stmt = stmt.where(TemplateTestRun.template_id == template_id)
        return self.session.scalars(
            stmt.order_by(TemplateTestRun.created_at.desc()).limit(10)
        ).all()

    @staticmethod
    def to_read(run: TemplateTestRun) -> TestRunRead:
        results = [TestResult.model_validate(r) for r in run.results]
        return TestRunRead(
            id=run.id,
            template_id=run.template_id,
            template_version=run.template_version,
            status=run.status,
            total_calls=run.total_calls,
            completed_calls=len(results),
            estimated_cost_usd=run.estimated_cost_usd,
            actual_cost_usd=run.actual_cost_usd,
            error=run.error,
            config=dict(run.config),
            results=results,
            summary=summarize(results, list(run.config.get("models", []))),
            created_at=run.created_at,
            created_by=run.created_by,
        )


def execute_test_run(
    session_factory: sessionmaker[Session],
    writer: DraftWriter | None,
    job_id: uuid.UUID,
    *,
    parallel: int = PARALLEL_DRAFTS,
) -> None:
    """Worker handler for "template_test" jobs."""
    with session_factory() as session:
        job = session.get(Job, job_id)
        run = session.get(TemplateTestRun, uuid.UUID(job.payload["run_id"])) if job else None
        if job is None or run is None:
            return
        if writer is None:
            run.status = "failed"
            run.error = "AI drafting isn't set up: add ANTHROPIC_API_KEY to the environment."
            job.status = "done"
            session.commit()
            return
        req = TestRunCreate.model_validate(run.config)
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None
        inputs = TemplateTestService(session).inputs(run.tenant_id, req)
        run.status = "running"
        session.commit()
        run_id, business = run.id, tenant.name

    content = _content(req.template)
    tasks = [
        (ref, label, inp, model, n)
        for model in req.models
        for ref, label, inp in inputs
        for n in range(1, req.runs_per_input + 1)
    ]

    def draft(task: tuple[str, str, DraftInput, str, int]) -> TestResult:
        ref, label, inp, model, n = task
        try:
            info = generate_draft(
                writer,
                business_name=business,
                template_name=req.template.name,
                template_id=req.template_id,
                template_version=None,
                content=content.model_copy(update={"model": model}),
                draft_input=inp,
            )
            return TestResult(
                input_ref=ref, input_label=label, model=model, run=n, ok=True, draft=info
            )
        except DraftError as exc:
            return TestResult(
                input_ref=ref, input_label=label, model=model, run=n, ok=False, error=str(exc)
            )

    def save(result: TestResult) -> None:
        with session_factory() as session:
            saved = session.get(TemplateTestRun, run_id)
            assert saved is not None
            saved.results = [*saved.results, result.model_dump(mode="json")]
            if result.draft:
                saved.actual_cost_usd += result.draft.cost_usd
            session.commit()

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(draft, t) for t in tasks]
        for future in as_completed(futures):
            save(future.result())  # results are written from this thread only

    with session_factory() as session:
        saved = session.get(TemplateTestRun, run_id)
        job = session.get(Job, job_id)
        assert saved is not None and job is not None
        saved.status = "done"
        job.status = "done"
        session.commit()
