"""Connector management and the live connector test (Operations Portal)."""

import uuid
from collections.abc import Sequence

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.context import contexts_for
from app.connectors.runner import RunSettings, run_connector
from app.domain.errors import ConflictError, NotFoundError
from app.models import Connector
from app.models.base import utcnow
from app.repositories import (
    CaseRepository,
    ConnectorRepository,
    MessageRepository,
    TenantRepository,
)
from app.schemas import ConnectorRead, ConnectorTestRequest, ConnectorTestResult, ConnectorWrite
from app.security.secrets import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.security.ssrf import Resolver


def to_read(connector: Connector) -> ConnectorRead:
    return ConnectorRead.model_validate(
        {
            **{c.key: getattr(connector, c.key) for c in Connector.__table__.columns},
            "has_secret": connector.secret_ciphertext is not None,
        }
    )


def run_settings(settings: Settings, resolve: Resolver) -> RunSettings:
    return RunSettings(
        allow_http=settings.connector_allow_http,
        allowed_hosts=settings.connector_allowed_hosts,
        max_response_bytes=settings.connector_max_response_bytes,
        resolve=resolve,
    )


class ConnectorService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.connectors = ConnectorRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)

    def _require_tenant(self, tenant_id: uuid.UUID) -> None:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

    def list(self, tenant_id: uuid.UUID) -> Sequence[Connector]:
        self._require_tenant(tenant_id)
        return self.connectors.list(tenant_id)

    def get(self, tenant_id: uuid.UUID, connector_id: uuid.UUID) -> Connector:
        connector = self.connectors.get(tenant_id, connector_id)
        if connector is None:
            raise NotFoundError(f"Connector {connector_id} not found.")
        return connector

    def create(self, tenant_id: uuid.UUID, data: ConnectorWrite) -> Connector:
        self._require_tenant(tenant_id)
        connector = Connector(tenant_id=tenant_id)
        self._apply(connector, data)
        self.connectors.add(connector)
        self._commit_unique_key(data.key)
        return connector

    def replace(
        self, tenant_id: uuid.UUID, connector_id: uuid.UUID, data: ConnectorWrite
    ) -> Connector:
        """Full update (the editor always sends the whole connector).

        The secret only changes if a new one is sent, or `clear_secret` is set.
        """
        connector = self.get(tenant_id, connector_id)
        self._apply(connector, data)
        connector.updated_at = utcnow()
        self._commit_unique_key(data.key)
        return connector

    def _apply(self, connector: Connector, data: ConnectorWrite) -> None:
        config = data.model_dump(exclude={"secret", "clear_secret"})
        for name, value in config.items():
            setattr(connector, name, value)
        if data.clear_secret:
            connector.secret_ciphertext = None
        elif data.secret:
            connector.secret_ciphertext = encrypt_secret(data.secret)

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
        client: httpx.Client,
        settings: Settings,
        resolve: Resolver,
    ) -> ConnectorTestResult:
        """Run the (possibly unsaved) connector against a real case. Saves nothing.

        Returns the full response so the editor can offer fields to map.
        """
        case = self.cases.get_by_number(tenant_id, req.case_number)
        if case is None:
            raise NotFoundError(f"Case {req.case_number} not found.")

        secret = req.draft.secret
        if not secret and req.connector_id and not req.draft.clear_secret:
            stored = self.get(tenant_id, req.connector_id).secret_ciphertext
            if stored:
                try:
                    secret = decrypt_secret(stored)
                except SecretDecryptionError as exc:
                    return ConnectorTestResult(status="failed", error=str(exc))

        texts = self.messages.customer_texts(tenant_id, case.id)
        template_context, routing_context = contexts_for(case, texts)
        return run_connector(
            req.draft,
            template_context=template_context,
            routing_context=routing_context,
            secret=secret,
            client=client,
            settings=run_settings(settings, resolve),
        )
