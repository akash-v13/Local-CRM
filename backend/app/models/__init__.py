"""Database models (one class per table).

Every model must be imported here. Alembic imports this package to discover
all tables when generating migrations — a model missing from this file is
invisible to migrations.
"""

from app.models.base import Base
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.connector import Connector
from app.models.credential import Credential
from app.models.customer import Customer
from app.models.job import Job
from app.models.message import Message
from app.models.queue import Queue
from app.models.reply_template import (
    ReplyTemplate,
    ReplyTemplateVersion,
    SampleCase,
    TemplateTestRun,
)
from app.models.tenant import Tenant

__all__ = [
    "Base",
    "Case",
    "CaseEvent",
    "Connector",
    "Credential",
    "Customer",
    "Job",
    "Message",
    "Queue",
    "ReplyTemplate",
    "ReplyTemplateVersion",
    "SampleCase",
    "TemplateTestRun",
    "Tenant",
]
