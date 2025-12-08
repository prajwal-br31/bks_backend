"""Accounting domain enums."""

from enum import Enum as PyEnum


class AccountType(str, PyEnum):
    """Chart of Accounts account types."""
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class SourceModule(str, PyEnum):
    """Source module for journal entries."""
    AR = "ar"  # Accounts Receivable
    AP = "ap"  # Accounts Payable
    BANK = "bank"  # Bank Feed
    MANUAL = "manual"  # Manual entry
    SYSTEM = "system"  # System-generated


class JournalStatus(str, PyEnum):
    """Journal entry status."""
    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"


class InvoiceStatus(str, PyEnum):
    """AR Invoice status."""
    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class BillStatus(str, PyEnum):
    """AP Bill status."""
    DRAFT = "draft"
    APPROVED = "approved"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"
