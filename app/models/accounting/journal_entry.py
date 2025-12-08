"""Journal Entry and Journal Line models."""

from datetime import datetime, date
from uuid import uuid4, UUID
from sqlalchemy import String, Date, DateTime, Enum, ForeignKey, Numeric, CheckConstraint
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import Base
from app.domain.accounting.enums import SourceModule, JournalStatus


class JournalEntry(Base):
    """Journal Entry model."""
    
    __tablename__ = "journal_entries"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    source_module: Mapped[SourceModule] = mapped_column(Enum(SourceModule), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    status: Mapped[JournalStatus] = mapped_column(
        Enum(JournalStatus), 
        default=JournalStatus.DRAFT,
        nullable=False
    )
    
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", 
        back_populates="entry", 
        cascade="all, delete-orphan"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )


class JournalLine(Base):
    """Journal Line model."""
    
    __tablename__ = "journal_lines"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    journal_entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False
    )
    
    # Relationship
    entry: Mapped[JournalEntry] = relationship("JournalEntry", back_populates="lines")
    
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id"),
        nullable=False
    )
    
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    debit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
    
    __table_args__ = (
        CheckConstraint("debit >= 0", name="check_debit_non_negative"),
        CheckConstraint("credit >= 0", name="check_credit_non_negative"),
    )
