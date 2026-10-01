"""Connector management and the live connector test (Operations Portal)."""

import uuid
from collections.abc import Sequence

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.connectors.auth import AuthProvider
from app.connectors.context import contexts_for
from app.connectors.runner import AuthSource, run_connector
from app.connectors.runner_settings import RunSettings
from app.domain.errors import ConflictError, NotFoundError
from app.models import Connector
from app.models.base import utcnow
from app.repositories import (
    CaseRepository,
    ConnectorRepository,
    CredentialRepository,
    MessageRepository,
    TenantRepository,
)
from app.schemas import ConnectorConfig, ConnectorRead, ConnectorTestRequest, ConnectorTestResult
from app.security.ssrf import Resolver


def to_read(connector: Connector) -> ConnectorRead:
    return ConnectorRead.model_validate(
        {c.key: getattr(connector, c.key) for c in Connector.__table__.columns}
    )


def run_settings(settings: Settings, resolve: Resolver) -> RunSettings:
    return RunSettings(
        allow_http=settings.connector_allow_http,
        allowed_hosts=settings.connector_allowed_hosts,
        max_response_bytes=settings.connector_max_response_bytes,
        resolve=resolve,
    )


def auth_source(credential_id: uuid.UUID | None, provider: AuthProvider) -> AuthSource | None:
    if credential_id is None:
        return None
    return lambda force_refresh: provider.headers_for(credential_id, force_refresh=force_refresh)


class ConnectorService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.connectors = ConnectorRepository(session)
        self.credentials = CredentialRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)

    def _require_tenant(self, tenant_id: uuid.UUID) -> None:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

    def _check_credential(self, tenant_id: uuid.UUID, data: ConnectorConfig) -> None:
        if data.credential_id and self.credentials.get(tenant_id, data.credential_id) is None:
            raise NotFoundError(f"Credential {data.credential_id} not found.")

    def list(self, tenant_id: uuid.UUID) -> Sequence[Connector]:
        self._require_tenant(tenant_id)
        return self.connectors.list(tenant_id)

    def get(self, tenant_id: uuid.UUID, connector_id: uuid.UUID) -> Connector:
        connector = self.connectors.get(tenant_id, connector_id)
        if connector is None:
            raise NotFoundError(f"Connector {connector_id} not found.")
        return connector

    def create(self, tenant_id: uuid.UUID, data: ConnectorConfig) -> Connector:
        self._require_tenant(tenant_id)
        self._check_credential(tenant_id, data)
        connector = Connector(tenant_id=tenant_id, **data.model_dump())
        self.connectors.add(connector)
        self._commit_unique_key(data.key)
        return connector

    def replace(
        self, tenant_id: uuid.UUID, connector_id: uuid.UUID, data: ConnectorConfig
    ) -> Connector:
        """Full update: the editor always sends the whole connector."""
        connector = self.get(tenant_id, connector_id)
        self._check_credential(tenant_id, data)
        for name, value in data.model_dump().items():
            setattr(connector, name, value)
        connector.updated_at = utcnow()
        self._commit_unique_key(data.key)
        return connector

    def _commit_unique_key(self, key: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if "key" in str(exc.orig):
                raise ConflictError(f"Another connector already uses the key '{key}'.") from exc
            raise

    def test(
        self,
        tenant_id: uuid.UUID,
        req: ConnectorTestRequest,
        *,
        session_factory: sessionmaker[Session],
        client: httpx.Client,
        settings: Settings,
        resolve: Resolver,
    ) -> ConnectorTestResult:
        """Run the (possibly unsaved) connector against a real case. Saves nothing
        except a generated token, if its credential needed a fresh one.

        Returns the full response so the editor can offer fields to map.
        """
        case = self.cases.get_by_number(tenant_id, req.case_number)
        if case is None:
            raise NotFoundError(f"Case {req.case_number} not found.")
        self._check_credential(tenant_id, req.draft)

        runner_settings = run_settings(settings, resolve)
        provider = AuthProvider(session_factory, client, runner_settings)
        texts = self.messages.customer_texts(tenant_id, case.id)
        template_context, routing_context = contexts_for(case, texts)
        return run_connector(
            req.draft,
            template_context=template_context,
            routing_context=routing_context,
            auth=auth_source(req.draft.credential_id, provider),
            client=client,
            settings=runner_settings,
        )
