"""Pydantic schemas for request/response validation."""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, List, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
    ValidatorFunctionWrapHandler,
)

from app.core.config import TIMEZONE


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def to_naive_jakarta(dt: datetime) -> datetime:
    """
    Convert a datetime to naive Jakarta time (UTC+7) for PostgreSQL.
    
    - If timezone-aware: convert to Jakarta, then strip tzinfo
    - If naive: assume it's already in Jakarta time
    """
    if dt.tzinfo is not None:
        # Convert to Jakarta timezone and strip tzinfo
        return dt.astimezone(TIMEZONE).replace(tzinfo=None)
    return dt


# ============================================================================
# ENUMS (Replace magic strings)
# ============================================================================


class DocumentStatus(str, Enum):
    """Status for documents (Receiving, Outgoing, Request)."""
    DRAFT = "draft"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StockStatusFilter(str, Enum):
    """Filter options for stock status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


class MovementType(str, Enum):
    """Type of stock movement."""
    IN = "in"
    OUT = "out"


class ReferenceType(str, Enum):
    """Reference document type for movements."""
    RECEIVINGS = "Receivings"
    OUTGOINGS = "Outgoings"


# ============================================================================
# PAGINATION
# ============================================================================

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    items: list[T]
    total: int
    page: int
    limit: int
    
    @property
    def pages(self) -> int:
        """Calculate total number of pages."""
        return (self.total + self.limit - 1) // self.limit if self.limit > 0 else 0
    
    @property
    def has_next(self) -> bool:
        """Check if there's a next page."""
        return self.page < self.pages
    
    @property
    def has_prev(self) -> bool:
        """Check if there's a previous page."""
        return self.page > 1


# ============================================================================
# USER SCHEMAS
# ============================================================================


class UserCreate(BaseModel):
    """Schema for creating a user."""
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    permissions: list[str] | None = None


class UserResponse(BaseModel):
    """Schema for user response (excludes sensitive fields)."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str
    email: str
    permissions: list[str]
    email_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# PART SCHEMAS
# ============================================================================


class PartCreate(BaseModel):
    """Schema for creating a part."""
    part_number: str = Field(..., min_length=1, max_length=255)
    part_name: str = Field(..., min_length=1, max_length=255)
    customer_code: str | None = Field(default=None, max_length=255)
    supplier_code: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    variant: str | None = Field(default=None, max_length=255)
    standard_packing: int = Field(default=1, ge=1)
    stock: int = Field(default=0, ge=0)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class PartUpdate(BaseModel):
    """Schema for updating a part."""
    part_number: str | None = Field(default=None, min_length=1, max_length=255)
    part_name: str | None = Field(default=None, min_length=1, max_length=255)
    customer_code: str | None = Field(default=None, max_length=255)
    supplier_code: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    variant: str | None = Field(default=None, max_length=255)
    standard_packing: int | None = Field(default=None, ge=1)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

class PickRequest(BaseModel):
    part_number: str

class PartResponse(BaseModel):
    """Schema for part response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    part_number: str
    part_name: str
    customer_code: str | None = None
    supplier_code: str | None = None
    model: str | None = None
    variant: str | None = None
    standard_packing: int
    stock: int
    address: str | None = None
    is_active: bool
    stock_status: str  # Computed: in_stock, low_stock, out_of_stock
    created_at: datetime
    updated_at: datetime


# ============================================================================
# RECEIVING SCHEMAS
# ============================================================================


class ReceivingItemCreate(BaseModel):
    """Schema for creating a receiving item."""
    part_id: UUID
    qty: int = Field(..., gt=0)


class ReceivingItemResponse(BaseModel):
    """Schema for receiving item response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    receiving_id: UUID
    part_id: UUID
    qty: int
    created_at: datetime
    updated_at: datetime


class ReceivingCreate(BaseModel):
    """Schema for creating a receiving."""
    doc_number: str = Field(..., min_length=1, max_length=255)
    received_by: UUID
    received_at: datetime
    notes: str | None = None
    items: list[ReceivingItemCreate] = Field(..., min_length=1)

    @field_validator("received_at", mode="before")
    @classmethod
    def convert_to_naive(cls, v: Any) -> datetime:
        """Convert timezone-aware datetime to naive Jakarta time (UTC+7)."""
        if isinstance(v, datetime):
            return to_naive_jakarta(v)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return to_naive_jakarta(dt)
        return v


class ReceivingUpdate(BaseModel):
    """Schema for updating a receiving."""
    doc_number: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    items: list[ReceivingItemCreate] | None = None


class ReceivingResponse(BaseModel):
    """Schema for receiving response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    doc_number: str
    received_by: UUID
    received_at: datetime
    status: str
    notes: str | None = None
    is_gr: bool
    total_items: int
    items: list[ReceivingItemResponse]
    created_at: datetime
    updated_at: datetime


# ============================================================================
# OUTGOING SCHEMAS
# ============================================================================


class OutgoingItemCreate(BaseModel):
    """Schema for creating an outgoing item."""
    part_id: UUID
    qty: int = Field(..., gt=0)


class OutgoingItemResponse(BaseModel):
    """Schema for outgoing item response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    outgoing_id: UUID
    part_id: UUID
    qty: int
    created_at: datetime
    updated_at: datetime


class OutgoingCreate(BaseModel):
    """Schema for creating an outgoing."""
    doc_number: str = Field(..., min_length=1, max_length=255)
    issued_by: UUID
    issued_at: datetime
    notes: str | None = None
    items: list[OutgoingItemCreate] = Field(..., min_length=1)

    @field_validator("issued_at", mode="before")
    @classmethod
    def convert_to_naive(cls, v: Any) -> datetime:
        """Convert timezone-aware datetime to naive Jakarta time (UTC+7)."""
        if isinstance(v, datetime):
            return to_naive_jakarta(v)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return to_naive_jakarta(dt)
        return v


class OutgoingUpdate(BaseModel):
    """Schema for updating an outgoing."""
    doc_number: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    items: list[OutgoingItemCreate] | None = None


class OutgoingResponse(BaseModel):
    """Schema for outgoing response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    doc_number: str
    issued_by: UUID
    issued_at: datetime
    status: str
    notes: str | None = None
    is_gi: bool
    total_items: int
    items: list[OutgoingItemResponse]
    created_at: datetime
    updated_at: datetime


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================


class RequestListCreate(BaseModel):
    """Schema for creating a request list item."""
    part_id: UUID
    qty: int = Field(..., gt=0)
    is_urgent: bool = False


class RequestListResponse(BaseModel):
    """Schema for request list item response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    request_id: UUID
    part_id: UUID
    qty: int
    is_urgent: bool
    is_supplied: bool
    created_at: datetime
    updated_at: datetime


class RequestCreate(BaseModel):
    """Schema for creating a request."""
    request_number: str = Field(..., min_length=1, max_length=255)
    requested_by: UUID
    requested_at: datetime
    destination: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    items: list[RequestListCreate] = Field(..., min_length=1)

    @field_validator("requested_at", mode="before")
    @classmethod
    def convert_to_naive(cls, v: Any) -> datetime:
        """Convert timezone-aware datetime to naive Jakarta time (UTC+7)."""
        if isinstance(v, datetime):
            return to_naive_jakarta(v)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return to_naive_jakarta(dt)
        return v


class RequestUpdate(BaseModel):
    """Schema for updating a request."""
    request_number: str | None = Field(default=None, min_length=1, max_length=255)
    destination: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    items: list[RequestListCreate] | None = None


class RequestResponse(BaseModel):
    """Schema for request response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    request_number: str
    requested_by: UUID
    requested_by_name: str | None = None
    requested_at: datetime
    destination: str | None = None
    status: str
    notes: str | None = None
    items: list[RequestListResponse]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="wrap")
    @classmethod
    def extract_user_name(cls, values: Any, handler: ValidatorFunctionWrapHandler) -> "RequestResponse":
        """Extract user name from relationship if available."""
        if hasattr(values, "requested_by_user") and values.requested_by_user:
            result = handler(values)
            result.requested_by_name = values.requested_by_user.name
            return result
        return handler(values)


# ============================================================================
# PART MOVEMENT SCHEMAS
# ============================================================================


class PartMovementResponse(BaseModel):
    """Schema for part movement response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    part_id: UUID
    stock_before: int
    type: str  # "in" or "out"
    qty: int
    stock_after: int
    reference_type: str  # "Receivings" or "Outgoings"
    reference_id: UUID
    created_at: datetime

class PingResponse(BaseModel):
    success: bool
    message: str
    timestamp: str

class MovementSyncItem(BaseModel):
    """Simplified movement data for Google Sheets sync."""
    part_number: str
    date: str  # YYYY-MM-DD format
    time: str  # HH:MM:SS format
    type: str  # IN or OUT
    qty: int


class MovementSyncResponse(BaseModel):
    """Response model for Google Sheets sync."""
    success: bool = True
    data: List[MovementSyncItem]
    total: int


# ============================================================================
# AUTH SCHEMAS
# ============================================================================


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Schema for token response."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============================================================================
# DASHBOARD SCHEMAS
# ============================================================================


class PartsStats(BaseModel):
    """Statistics for parts."""
    total: int
    active: int
    in_stock: int
    low_stock: int
    out_of_stock: int


class ReceivingsStats(BaseModel):
    """Statistics for receivings."""
    total: int
    draft: int
    completed: int
    pending_gr: int


class OutgoingsStats(BaseModel):
    """Statistics for outgoings."""
    total: int
    draft: int
    completed: int
    pending_gi: int


class RequestsStats(BaseModel):
    """Statistics for requests."""
    total: int
    draft: int
    completed: int


class DashboardStats(BaseModel):
    """Aggregated statistics for dashboard."""
    parts: PartsStats
    receivings: ReceivingsStats
    outgoings: OutgoingsStats
    requests: RequestsStats


class DashboardResponse(BaseModel):
    """Complete dashboard response with stats and recent items."""
    stats: DashboardStats
    recent_receivings: list[ReceivingResponse]
    recent_outgoings: list[OutgoingResponse]
    low_stock_parts: list[PartResponse]
    pending_requests: list[RequestResponse]
    recent_movements: list[PartMovementResponse]
