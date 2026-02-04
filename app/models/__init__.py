"""SQLAlchemy ORM models for all resources."""

import uuid
from datetime import datetime, timezone
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import now_jakarta


class Base(DeclarativeBase):
    pass


class SoftDeleteMixin:
    """Mixin for soft delete behavior - provides deleted_at field and soft_delete method."""
    
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    
    def soft_delete(self) -> None:
        """Mark the record as deleted."""
        self.deleted_at = datetime.now(timezone.utc)
    
    @property
    def is_deleted(self) -> bool:
        """Check if the record is soft-deleted."""
        return self.deleted_at is not None


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, onupdate=now_jakarta, nullable=False)


class User(TimestampMixin, Base):
    """User model with permissions and 2FA support."""

    __tablename__ = "users"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    two_factor_recovery_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    two_factor_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remember_token: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    receivings: Mapped[list["Receiving"]] = relationship("Receiving", back_populates="received_by_user", foreign_keys="Receiving.received_by")
    outgoings: Mapped[list["Outgoing"]] = relationship("Outgoing", back_populates="issued_by_user", foreign_keys="Outgoing.issued_by")
    requests: Mapped[list["Request"]] = relationship("Request", back_populates="requested_by_user", foreign_keys="Request.requested_by")

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions


class Part(SoftDeleteMixin, TimestampMixin, Base):
    """Parts/inventory model with stock tracking."""

    __tablename__ = "parts"
    __table_args__ = (
        Index("ix_parts_part_number", "part_number"),
        Index("ix_parts_deleted_at", "deleted_at"),
        Index("ix_parts_is_active", "is_active"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_number: Mapped[str] = mapped_column(String(255), nullable=False)
    part_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    standard_packing: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    receiving_items: Mapped[list["ReceivingItem"]] = relationship("ReceivingItem", back_populates="part")
    outgoing_items: Mapped[list["OutgoingItem"]] = relationship("OutgoingItem", back_populates="part")
    movements: Mapped[list["PartMovement"]] = relationship("PartMovement", back_populates="part")

    @property
    def stock_status(self) -> str:
        """Compute stock status based on current stock level."""
        if self.stock <= 0:
            return "out_of_stock"
        elif self.stock <= 10:
            return "low_stock"
        else:
            return "in_stock"

    def has_transactions(self) -> bool:
        """Check if part exists in any ReceivingItems or OutgoingItems."""
        return len(self.receiving_items) > 0 or len(self.outgoing_items) > 0


class Receiving(SoftDeleteMixin, TimestampMixin, Base):
    """Incoming goods receipt model."""

    __tablename__ = "receivings"
    __table_args__ = (
        Index("ix_receivings_doc_number", "doc_number"),
        Index("ix_receivings_status", "status"),
        Index("ix_receivings_deleted_at", "deleted_at"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    received_by: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)  # draft, completed, cancelled
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_gr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    received_by_user: Mapped["User"] = relationship("User", back_populates="receivings", foreign_keys=[received_by])
    items: Mapped[list["ReceivingItem"]] = relationship("ReceivingItem", back_populates="receiving", cascade="all, delete-orphan")
    movements: Mapped[list["PartMovement"]] = relationship("PartMovement", foreign_keys="[PartMovement.reference_id]", primaryjoin="and_(Receiving.id==foreign(PartMovement.reference_id), PartMovement.reference_type=='Receivings')", viewonly=True)

    def is_editable(self) -> bool:
        """Check if receiving can be edited."""
        return not self.is_gr and self.status != "cancelled"

    def can_be_gr_confirmed(self) -> bool:
        """Check if receiving can be confirmed as GR."""
        return self.status == "completed" and not self.is_gr

    @property
    def total_items(self) -> int:
        """Compute total quantity of items in this receiving."""
        return sum(item.qty for item in self.items)


class ReceivingItem(TimestampMixin, Base):
    """Line item for a Receiving."""

    __tablename__ = "receiving_items"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receiving_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("receivings.id"), nullable=False)
    part_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    receiving: Mapped["Receiving"] = relationship("Receiving", back_populates="items")
    part: Mapped["Part"] = relationship("Part", back_populates="receiving_items")


class Outgoing(SoftDeleteMixin, TimestampMixin, Base):
    """Outgoing goods issue model."""

    __tablename__ = "outgoings"
    __table_args__ = (
        Index("ix_outgoings_doc_number", "doc_number"),
        Index("ix_outgoings_status", "status"),
        Index("ix_outgoings_deleted_at", "deleted_at"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    issued_by: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)  # draft, completed, cancelled
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_gi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    issued_by_user: Mapped["User"] = relationship("User", back_populates="outgoings", foreign_keys=[issued_by])
    items: Mapped[list["OutgoingItem"]] = relationship("OutgoingItem", back_populates="outgoing", cascade="all, delete-orphan")
    movements: Mapped[list["PartMovement"]] = relationship("PartMovement", foreign_keys="[PartMovement.reference_id]", primaryjoin="and_(Outgoing.id==foreign(PartMovement.reference_id), PartMovement.reference_type=='Outgoings')", viewonly=True)

    def is_editable(self) -> bool:
        """Check if outgoing can be edited."""
        return not self.is_gi and self.status != "cancelled"

    def can_be_gi_confirmed(self) -> bool:
        """Check if outgoing can be confirmed as GI."""
        return self.status == "completed" and not self.is_gi

    @property
    def total_items(self) -> int:
        """Compute total quantity of items in this outgoing."""
        return sum(item.qty for item in self.items)


class OutgoingItem(TimestampMixin, Base):
    """Line item for an Outgoing."""

    __tablename__ = "outgoing_items"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outgoing_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outgoings.id"), nullable=False)
    part_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    outgoing: Mapped["Outgoing"] = relationship("Outgoing", back_populates="items")
    part: Mapped["Part"] = relationship("Part", back_populates="outgoing_items")


class Request(SoftDeleteMixin, TimestampMixin, Base):
    """Parts request model."""

    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_request_number", "request_number"),
        Index("ix_requests_status", "status"),
        Index("ix_requests_deleted_at", "deleted_at"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    requested_by: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)  # draft, completed, cancelled
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    requested_by_user: Mapped["User"] = relationship("User", back_populates="requests", foreign_keys=[requested_by])
    items: Mapped[list["RequestList"]] = relationship("RequestList", back_populates="request", cascade="all, delete-orphan")


class RequestList(TimestampMixin, Base):
    """Line item for a Request."""

    __tablename__ = "request_lists"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=False)
    part_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_supplied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    request: Mapped["Request"] = relationship("Request", back_populates="items")
    part: Mapped["Part"] = relationship("Part")


class PartMovement(Base):
    """Immutable audit trail for stock changes. Append-only, never update/delete."""

    __tablename__ = "part_movements"
    __table_args__ = (
        Index("ix_part_movements_part_id", "part_id"),
        Index("ix_part_movements_created_at", "created_at"),
        Index("ix_part_movements_reference", "reference_type", "reference_id"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # "in" or "out"
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "Receivings" or "Outgoings"
    reference_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jakarta, nullable=False)

    # Relationships
    part: Mapped["Part"] = relationship("Part", back_populates="movements")


__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
    "Part",
    "Receiving",
    "ReceivingItem",
    "Outgoing",
    "OutgoingItem",
    "Request",
    "RequestList",
    "PartMovement",
]
