from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class Tenant(IdMixin, CreatedAtMixin, Base):
    """A business using the platform. Every other table carries a `tenant_id`."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
