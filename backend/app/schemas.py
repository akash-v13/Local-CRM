"""API request/response shapes (Pydantic).

These are the *public contract* of the API and are deliberately separate from
the database models: the database can change shape without breaking API
clients, and we never accidentally expose internal columns.

Naming: `XCreate` = request body to create X, `XRead` = what the API returns.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.lifecycle import CaseStatus
from app.domain.routing import LIST_OPERATORS, Operator, is_known_field

ActorType = Literal["customer", "human", "ai", "system"]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class CustomerIn(BaseModel):
    email: EmailStr
    display_name: str | None = None
    tier: str | None = None


class CategoryIn(BaseModel):
    type: str
    category: str
    subcategory: str | None = None


class CaseCreate(BaseModel):
    """Intake payload: what a webform, email parser or helpdesk add-on sends."""

    channel: Literal["webform", "email", "chat", "api"]
    language: str = "en"
    customer: CustomerIn
    category: CategoryIn | None = Field(
        default=None, description="Category the customer selected, if the channel has one."
    )
    message: str = Field(min_length=1, description="The customer's first message.")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Tenant-defined fields, e.g. order number."
    )


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    channel: str
    author_type: str
    author_id: str | None
    visibility: str
    body: str
    ai: dict[str, Any]
    created_at: datetime


class CustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    tier: str | None


class QueueSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_number: int = Field(
        description="Public case ID: creation time in Unix microseconds. Used in API paths."
    )
    id: uuid.UUID = Field(description="Internal id. Prefer case_number.")
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    customer: CustomerSummary
    status: CaseStatus
    status_changed_at: datetime
    channel: str
    language: str
    category: dict[str, Any]
    attributes: dict[str, Any]
    flags: dict[str, Any]
    sla: dict[str, Any]
    enrichment: dict[str, Any]
    decisions: dict[str, Any]
    queue_id: uuid.UUID | None
    queue: QueueSummary | None
    assignee_type: str | None
    assignee_id: str | None
    assignment_pinned: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseRead):
    """A case plus its full message thread and the statuses it can move to next."""

    messages: list[MessageRead]
    allowed_next_statuses: list[CaseStatus] = Field(
        description="Valid targets for POST .../transitions from the current status."
    )


class MessageCreate(BaseModel):
    kind: Literal["agent_reply", "internal_note", "customer_reply"] = Field(
        description=(
            "agent_reply: sent to the customer (simulated for now). "
            "internal_note: agents only. "
            "customer_reply: simulates the customer writing back (for testing)."
        )
    )
    body: str = Field(min_length=1)
    author_id: str | None = Field(
        default=None, description="Agent identifier. Ignored for customer_reply."
    )
    then_status: CaseStatus | None = Field(
        default=None,
        description="agent_reply only: move the case to this status in the same transaction.",
    )


class TransitionRequest(BaseModel):
    to_status: CaseStatus
    actor_type: ActorType
    actor_id: str | None = None
    reason: str | None = None
    expected_version: int | None = Field(
        default=None,
        description=(
            "Optional. The case `version` the caller last saw. If the case has changed "
            "since, the request is rejected with 409 instead of overwriting newer work."
        ),
    )


class CaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_type: str
    actor_id: str | None
    reason: str | None
    data: dict[str, Any]
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Queues and routing (Operations Portal)
# ---------------------------------------------------------------------------


class Condition(BaseModel):
    """One routing condition, e.g. category.category equals "Delivery"."""

    field: str = Field(
        description="A routing field (see GET .../routing/fields) or attributes.<key>."
    )
    op: Operator
    value: str | list[str]

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if not is_known_field(self.field):
            raise ValueError(f"Unknown field '{self.field}'.")
        if self.op in LIST_OPERATORS:
            if not isinstance(self.value, list) or not [v for v in self.value if v.strip()]:
                raise ValueError(f"'{self.op}' needs a non-empty list of values.")
            self.value = [v.strip() for v in self.value if v.strip()]
        elif not isinstance(self.value, str) or not self.value.strip():
            raise ValueError(f"'{self.op}' needs a single non-empty value.")
        return self


class MatchCriteria(BaseModel):
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(
        default_factory=list, description="Empty = matches every case (catch-all)."
    )


class QueueSettings(BaseModel):
    """How cases in this queue are handled.

    Stored and editable now; enforced as the matching features are built
    (AI drafting, approvals, SLAs).
    """

    gen_ai_allowed: bool = False
    auto_send: bool = False
    approval_threshold: float | None = Field(
        default=None, ge=0, description="Compensation above this amount needs approval."
    )
    sla_first_response_hours: int | None = Field(default=None, ge=1)
    reopen_window_hours: int | None = Field(default=72, ge=1)


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: int = Field(ge=0, description="Lower = checked first.")
    is_active: bool = True
    match_criteria: MatchCriteria = Field(default_factory=MatchCriteria)
    settings: QueueSettings = Field(default_factory=QueueSettings)


class QueueUpdate(BaseModel):
    """Partial update: only the fields you send are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    match_criteria: MatchCriteria | None = None
    settings: QueueSettings | None = None


class QueueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    is_active: bool
    match_criteria: MatchCriteria
    settings: QueueSettings
    created_at: datetime
    updated_at: datetime


class RerouteRequest(BaseModel):
    queue_id: uuid.UUID
    actor_id: str | None = None
    reason: str | None = None


class RouteRequest(BaseModel):
    actor_type: ActorType = "human"
    actor_id: str | None = None


class RoutingPreviewRequest(BaseModel):
    case_number: int
    draft: QueueCreate | None = Field(
        default=None, description="Unsaved queue settings to test (e.g. from the editor)."
    )
    draft_queue_id: uuid.UUID | None = Field(
        default=None, description="If the draft edits an existing queue, its id."
    )


class ConditionResultRead(BaseModel):
    field: str
    op: str
    value: str | list[str]
    matched: bool
    actual: Any
    description: str


class QueueEvaluationRead(BaseModel):
    queue_id: uuid.UUID | None
    queue_name: str
    priority: int
    matched: bool
    is_winner: bool
    is_draft: bool
    conditions: list[ConditionResultRead]


class RoutingPreview(BaseModel):
    winner_queue_id: uuid.UUID | None
    winner_queue_name: str | None
    evaluations: list[QueueEvaluationRead]


class RoutingField(BaseModel):
    key: str
    label: str
    suggestions: list[str]


class RoutingOperator(BaseModel):
    key: Operator
    label: str
    takes_list: bool


class RoutingFields(BaseModel):
    fields: list[RoutingField]
    operators: list[RoutingOperator]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class QueueReportRow(BaseModel):
    queue_id: uuid.UUID | None = Field(description="None = cases not routed to any queue.")
    queue_name: str
    priority: int | None
    is_active: bool
    counts: dict[CaseStatus, int] = Field(description="Cases per status (zeros omitted).")
    open_total: int = Field(description="Cases not Solved or Closed.")
    oldest_open_at: datetime | None


class QueueReport(BaseModel):
    generated_at: datetime
    totals: dict[CaseStatus, int]
    open_total: int
    rows: list[QueueReportRow]
