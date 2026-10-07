"""Reading customer messages at intake: field values (order number, …) and the category.

Where it fits in the intake pipeline:

    case received ──► ⓪ read the message ──► ① ② ③ connectors ──► routing ──► compensation

When a business turns reading on for a channel (email by default), `create_case`
queues a `read_case` job instead of going straight to enrichment. The job:

1. loads the message (subject + the customer's text) and the business's settings,
   then closes the database session;
2. finds candidates for each field (app/ai/reading.py) and asks the reader model
   (Jev, else Claude; app/ai/readers.py) to choose, with personal details masked;
3. saves confident values as `attributes.<key>` (never overwriting what the customer
   or an integration already provided) and, if the customer picked no category,
   the chosen one as the case's effective category (`source: "ai"`);
4. records everything on `case.extraction` (values, confidence, candidates, model,
   cost) with an event, and continues intake: enrichment, or routing.

A reading failure never blocks a case: it's recorded and intake continues.
Uncertain values wait for an agent, who picks from the candidates on the case.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.ai.pii import Masker
from app.ai.readers import FieldQuestion, Reader, ReaderError, ReadRequest, ReadResult
from app.ai.reading import (
    Candidate,
    FieldResult,
    Pick,
    category_options,
    decide_field,
    find_candidates,
)
from app.domain.errors import ConflictError, NotFoundError
from app.domain.taxonomy import DEFAULT_TAXONOMY
from app.models import Case, CaseEvent, Job, Tenant
from app.models.base import utcnow
from app.repositories import CaseRepository, MessageRepository, TenantRepository
from app.schemas import CategoryChange, FieldReview, ReadingPreviewRequest, ReadingSettingsData


def settings_of(tenant: Tenant) -> ReadingSettingsData:
    return ReadingSettingsData.model_validate(tenant.reading_settings or {})


def should_read(settings: ReadingSettingsData, case: Case) -> bool:
    """Reading runs if it's on for this channel and there's something to find."""
    if not settings.enabled or case.channel not in settings.channels:
        return False
    missing_field = any(f.key not in case.attributes for f in settings.fields)
    return missing_field or (settings.read_category and category_open(case))


def category_open(case: Case) -> bool:
    """Reading may set the category: none yet, or only an inbox default. A customer's or
    agent's choice is never replaced."""
    category = case.category or {}
    return not category.get("effective") or category.get("source") == "inbox"


@dataclass
class Reading:
    """A message read: per-field results, the category decision, and how it was made."""

    fields: list[FieldResult]
    category: dict[str, Any] | None
    model: str
    status: str  # ok | failed | patterns_only
    error: str | None
    input_tokens: int
    cost_usd: float
    latency_ms: int

    def as_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "error": self.error,
            "fields": [f.as_dict() for f in self.fields],
            "category": self.category,
            "input_tokens": self.input_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "read_at": utcnow().isoformat(),
        }


def read_message(
    reader: Reader | None,
    settings: ReadingSettingsData,
    *,
    subject: str,
    text: str,
    customer_name: str | None,
    customer_email: str | None,
    want_fields: set[str] | None = None,
    want_category: bool = True,
) -> Reading:
    """Candidates by pattern, then the model chooses; the decision rules are in decide_field.
    No database access, so it runs outside any transaction."""
    fields = [f for f in settings.fields if want_fields is None or f.key in want_fields]
    found: dict[str, list[Candidate]] = {
        f.key: find_candidates(f.pattern, f"{subject}\n{text}") for f in fields
    }
    options = (
        category_options(DEFAULT_TAXONOMY) if (settings.read_category and want_category) else {}
    )

    # The model sees the message with personal details masked, and only the candidates.
    masker = Masker(customer_name, customer_email)
    masked_subject, masked_text = masker.mask(subject), masker.mask(text)
    option_ids: dict[str, dict[str, str]] = {
        f.key: {f"c{i + 1}": c.value for i, c in enumerate(found[f.key])} for f in fields
    }
    questions = [
        FieldQuestion(
            key=f.key,
            description=f.description,
            options={
                f"c{i + 1}": f"{c.value} (in: “{masker.mask(c.context)}”)"
                for i, c in enumerate(found[f.key])
            },
        )
        for f in fields
        if found[f.key]
    ]
    result: ReadResult | None = None
    error: str | None = None
    if reader is not None and (questions or options):
        try:
            result = reader.read(
                ReadRequest(
                    subject=masked_subject,
                    text=masked_text,
                    fields=questions,
                    categories={k: v["label"] for k, v in options.items()} or None,
                )
            )
        except ReaderError as exc:
            error = str(exc)

    results = [
        decide_field(
            f.key,
            f.label,
            found[f.key],
            result.fields.get(f.key) if result else None,
            threshold=settings.min_confidence,
            option_ids=option_ids[f.key],
        )
        for f in fields
    ]
    category = _category_decision(
        result.category if result else None, options, settings.min_confidence
    )
    if result is not None:
        status, model = "ok", result.model
    elif error:
        status, model = "failed", reader.name if reader else "patterns"
    else:
        status, model = "patterns_only", "patterns"
    return Reading(
        fields=results,
        category=category,
        model=model,
        status=status,
        error=error,
        input_tokens=result.input_tokens if result else 0,
        cost_usd=result.cost_usd if result else 0.0,
        latency_ms=result.latency_ms if result else 0,
    )


def _category_decision(
    pick: Pick | None, options: dict[str, dict[str, Any]], threshold: float
) -> dict[str, Any] | None:
    if pick is None or not options:
        return None
    chosen = options.get(pick.option)
    return {
        "value": chosen["value"] if chosen else None,
        "label": chosen["label"] if chosen else "None of the categories fit",
        "confidence": pick.confidence,
        "confident": chosen is not None and pick.confidence >= threshold,
        "applied": False,
    }


# ----- the intake job --------------------------------------------------------------------


def queue_reading(session: Session, case: Case) -> None:
    """Add a read_case job (committed with the caller's transaction)."""
    session.add(Job(tenant_id=case.tenant_id, kind="read_case", case_id=case.id, max_attempts=1))
    session.add(
        CaseEvent(
            tenant_id=case.tenant_id,
            case_id=case.id,
            event_type="reading.queued",
            actor_type="system",
        )
    )


def read_case_job(
    session_factory: sessionmaker[Session], reader: Reader | None, job_id: uuid.UUID
) -> None:
    """Worker handler for `read_case`."""
    from app.services.cases import CaseService  # cases imports this module

    with session_factory() as session:
        job = session.get(Job, job_id)
        case = session.get(Case, job.case_id) if job and job.case_id else None
        tenant = session.get(Tenant, case.tenant_id) if case else None
        if job is None or case is None or tenant is None:
            return
        settings = settings_of(tenant)
        texts = MessageRepository(session).customer_texts(case.tenant_id, case.id)
        subject = str(case.attributes.get("subject") or "")
        want_fields = {f.key for f in settings.fields if f.key not in case.attributes}
        want_category = category_open(case)
        name, email, case_id = case.customer.display_name, case.customer.email, case.id

    started = time.monotonic()  # the model is called with no database session open
    reading = read_message(
        reader,
        settings,
        subject=subject,
        text="\n\n".join(texts),
        customer_name=name,
        customer_email=email,
        want_fields=want_fields,
        want_category=want_category,
    )
    reading.latency_ms = reading.latency_ms or int((time.monotonic() - started) * 1000)

    with session_factory() as session:
        case = session.get(Case, case_id)
        job = session.get(Job, job_id)
        if case is None or job is None:
            return
        attributes = dict(case.attributes)
        for f in reading.fields:
            if f.status == "found" and f.value and f.key not in attributes:
                attributes[f.key] = f.value
        case.attributes = attributes
        if reading.category and reading.category["confident"] and category_open(case):
            case.category = {
                **case.category,
                "effective": reading.category["value"],
                "source": "ai",
            }
            reading.category["applied"] = True
        case.extraction = reading.as_record()
        session.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="reading.completed",
                actor_type="ai" if reading.status == "ok" else "system",
                reason=reading.error,
                data={
                    "model": reading.model,
                    "status": reading.status,
                    "found": {f.key: f.value for f in reading.fields if f.status == "found"},
                    "needsReview": [f.key for f in reading.fields if f.status == "needs_review"],
                    "category": reading.category["label"]
                    if reading.category and reading.category["applied"]
                    else None,
                },
            )
        )
        CaseService(session).continue_intake(case)
        case.updated_at = utcnow()
        job.status = "done"
        session.commit()


# ----- settings, preview, review ------------------------------------------------------------


class ReadingService:
    def __init__(self, session: Session, reader: Reader | None) -> None:
        self.session = session
        self.reader = reader
        self.tenants = TenantRepository(session)
        self.cases = CaseRepository(session)

    def _tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def get_settings(self, tenant_id: uuid.UUID) -> ReadingSettingsData:
        return settings_of(self._tenant(tenant_id))

    def save_settings(self, tenant_id: uuid.UUID, data: ReadingSettingsData) -> ReadingSettingsData:
        tenant = self._tenant(tenant_id)
        tenant.reading_settings = data.model_dump()
        self.session.commit()
        return data

    def reader_name(self) -> str:
        return self.reader.name if self.reader else "patterns"

    def preview(self, tenant_id: uuid.UUID, req: ReadingPreviewRequest) -> dict[str, Any]:
        """Read a pasted message (or a real case's) with saved or unsaved settings.
        Nothing is saved. Calls the model (Jev: a fraction of a cent)."""
        settings = req.settings or self.get_settings(tenant_id)
        subject, text, name, email = req.subject, req.message, None, None
        if req.case_number is not None:
            case = self._case(tenant_id, req.case_number)
            subject = str(case.attributes.get("subject") or "")
            text = "\n\n".join(MessageRepository(self.session).customer_texts(tenant_id, case.id))
            name, email = case.customer.display_name, case.customer.email
        if not (subject or text).strip():
            raise ConflictError("Paste a message (or pick a case) to read.")
        reading = read_message(
            self.reader,
            settings,
            subject=subject,
            text=text,
            customer_name=name,
            customer_email=email,
        )
        return reading.as_record()

    def _case(self, tenant_id: uuid.UUID, case_number: int) -> Case:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        return case

    def confirm_field(
        self, tenant_id: uuid.UUID, case_number: int, key: str, req: FieldReview
    ) -> Case:
        """An agent sets a field (e.g. picks the right order number). Saved on the case
        and in the reading record; re-run enrichment afterwards to use it."""
        case = self._case(tenant_id, case_number)
        record = dict(case.extraction or {})
        fields = [dict(f) for f in record.get("fields", [])]
        match = next((f for f in fields if f["key"] == key), None)
        if match is None:
            raise NotFoundError(f"No field '{key}' was read on this case.")
        match.update(status="found", value=req.value, reviewed_by=req.actor_id)
        case.extraction = {**record, "fields": fields}
        case.attributes = {**case.attributes, key: req.value}
        self.session.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type="reading.field_confirmed",
                actor_type="human",
                actor_id=req.actor_id,
                data={"field": key, "value": req.value},
            )
        )
        case.updated_at = utcnow()
        self.session.commit()
        return case

    def change_category(self, tenant_id: uuid.UUID, case_number: int, req: CategoryChange) -> Case:
        """An agent sets the case's category (e.g. applies the suggestion). The customer's
        own choice is kept as `customerSelected`; re-run routing afterwards to use it."""
        case = self._case(tenant_id, case_number)
        previous = (case.category or {}).get("effective")
        value = req.category.model_dump()
        case.category = {**case.category, "effective": value, "source": "agent"}
        record = dict(case.extraction or {})
        if record.get("category"):
            record["category"] = {
                **record["category"],
                "applied": record["category"].get("value") == value,
            }
            case.extraction = record
        self.session.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type="case.recategorized",
                actor_type="human",
                actor_id=req.actor_id,
                reason=req.reason,
                data={"from": previous, "to": value},
            )
        )
        case.updated_at = utcnow()
        self.session.commit()
        return case
