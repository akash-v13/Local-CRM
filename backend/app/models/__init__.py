"""Database models (one class per table).

Every model must be imported here. Alembic imports this package to discover
all tables when generating migrations — a model missing from this file is
invisible to migrations.
"""

from app.models.base import Base
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.compensation_rule import CompensationRule
from app.models.connector import Connector
from app.models.credential import Credential
from app.models.customer import Customer
from app.models.job import Job
from app.models.mailbox import Mailbox
from app.models.message import Message
from app.models.prompt_template import (
    PromptTemplate,
    PromptTemplateVersion,
    SampleCase,
    TemplateTestRun,
)
from app.models.queue import Queue
from app.models.tenant import Tenant

__all__ = [
    "Base",
    "Case",
    "CaseEvent",
    "CompensationRule",
    "Connector",
    "Credential",
    "Customer",
    "Job",
    "Mailbox",
    "Message",
    "Queue",
    "PromptTemplate",
    "PromptTemplateVersion",
    "SampleCase",
    "TemplateTestRun",
    "Tenant",
]
