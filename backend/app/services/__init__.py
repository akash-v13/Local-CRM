"""Business operations (use cases), one module per area.

A service method = one complete business action = one database transaction.
It loads what it needs through repositories, applies domain rules, writes the
record AND its events together, and commits once. Either everything is saved
or nothing is.

Services know nothing about HTTP. They raise `app.domain.errors` exceptions,
which `app/main.py` maps to status codes. That lets the worker reuse them.
"""

from app.services.cases import CaseService
from app.services.connectors import ConnectorService
from app.services.credentials import CredentialService
from app.services.queues import QueueService
from app.services.reports import ReportService
from app.services.tenants import TenantService

__all__ = [
    "CaseService",
    "ConnectorService",
    "CredentialService",
    "QueueService",
    "ReportService",
    "TenantService",
]
