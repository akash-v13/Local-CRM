"""Credential management (Operations Portal → Integrations → Credentials)."""

import uuid
from collections.abc import Sequence

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.auth import (
    TOKEN_KINDS,
    AuthProvider,
    CredentialError,
    load_secrets,
    store_secrets,
)
from app.connectors.runner_settings import RunSettings
from app.domain.errors import ConflictError, NotFoundError
from app.models import Credential
from app.models.base import utcnow
from app.repositories import ConnectorRepository, CredentialRepository, TenantRepository
from app.schemas import CredentialRead, CredentialWrite, TokenStatus, TokenTestResult
from app.security.secrets import decrypt_secret


class CredentialService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.credentials = CredentialRepository(session)
        self.connectors = ConnectorRepository(session)

    def to_read(self, credential: Credential) -> CredentialRead:
        try:
            secret_fields = sorted(load_secrets(credential))
        except CredentialError:
            secret_fields = []
        token = None
        if credential.kind in TOKEN_KINDS:
            token = TokenStatus(
                cached=credential.token_ciphertext is not None,
                expires_at=credential.token_expires_at,
                fetched_at=credential.token_fetched_at,
            )
        used_by = [
            c.name
            for c in self.connectors.list(credential.tenant_id)
            if c.credential_id == credential.id
        ]
        return CredentialRead(
            id=credential.id,
            name=credential.name,
            kind=credential.kind,
            config=dict(credential.config),
            secret_fields=secret_fields,
            token=token,
            last_error=credential.last_error,
            used_by=used_by,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
        )

    def list(self, tenant_id: uuid.UUID) -> Sequence[Credential]:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return self.credentials.list(tenant_id)

    def get(self, tenant_id: uuid.UUID, credential_id: uuid.UUID) -> Credential:
        credential = self.credentials.get(tenant_id, credential_id)
        if credential is None:
            raise NotFoundError(f"Credential {credential_id} not found.")
        return credential

    def create(self, tenant_id: uuid.UUID, data: CredentialWrite) -> Credential:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        if data.secrets is None:
            data = data.model_copy(update={"secrets": {}})
            CredentialWrite.model_validate(data.model_dump())  # re-check required secrets
        credential = Credential(
            tenant_id=tenant_id, name=data.name, kind=data.kind, config=data.config
        )
        store_secrets(credential, data.secrets or {})
        self.credentials.add(credential)
        self._commit(data.name)
        return credential

    def replace(
        self, tenant_id: uuid.UUID, credential_id: uuid.UUID, data: CredentialWrite
    ) -> Credential:
        """Replace settings; secrets only if sent. Any change drops the cached token."""
        credential = self.get(tenant_id, credential_id)
        if data.kind != credential.kind and data.secrets is None:
            raise ConflictError("Changing the credential type needs new secret values.")
        credential.name = data.name
        credential.kind = data.kind
        credential.config = data.config
        if data.secrets is not None:
            store_secrets(credential, data.secrets)
        credential.token_ciphertext = None
        credential.token_expires_at = None
        credential.token_fetched_at = None
        credential.last_error = None
        credential.updated_at = utcnow()
        self._commit(data.name)
        return credential

    def _commit(self, name: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if "name" in str(exc.orig):
                raise ConflictError(f"A credential named '{name}' already exists.") from exc
            raise

    def test_token(
        self,
        tenant_id: uuid.UUID,
        credential_id: uuid.UUID,
        *,
        session_factory: sessionmaker[Session],
        client: httpx.Client,
        settings: RunSettings,
    ) -> TokenTestResult:
        """Generate a fresh token now (token kinds), or check the secrets decrypt (others)."""
        credential = self.get(tenant_id, credential_id)
        provider = AuthProvider(session_factory, client, settings)
        try:
            provider.headers_for(credential.id, force_refresh=True)
        except CredentialError as exc:
            return TokenTestResult(ok=False, error=str(exc))
        self.session.refresh(credential)
        if credential.kind not in TOKEN_KINDS:
            return TokenTestResult(ok=True)
        token = decrypt_secret(credential.token_ciphertext or "")
        preview = f"{token[:6]}… ({len(token)} characters)" if len(token) > 6 else "••••"
        return TokenTestResult(
            ok=True, token_preview=preview, expires_at=credential.token_expires_at
        )
