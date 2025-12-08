"""Chart of Accounts model."""

from datetime import datetime
from uuid import uuid4, UUID
from sqlalchemy import String, Boolean, Enum, Index
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import Base
from app.domain.accounting.enums import AccountType


class ChartOfAccount(Base):
    """Chart of Accounts model."""
    
    __tablename__ = "chart_of_accounts"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
    
    __table_args__ = (
        Index("idx_chart_of_accounts_company_code", "company_id", "code"),
    )
