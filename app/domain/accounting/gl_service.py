"""General Ledger service for journal entry operations."""

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import (
    JournalEntry,
    JournalLine,
    ChartOfAccount,
)
from app.domain.accounting.enums import (
    SourceModule,
    JournalStatus,
)

logger = logging.getLogger(__name__)


def create_journal_entry(
    db: Session,
    company_id: UUID,
    entry_date: date,
    description: str,
    source_module: SourceModule,
    source_id: UUID | None,
    lines_list: List[Dict[str, Any]],
) -> JournalEntry:
    """
    Create a journal entry with lines.
    
    Args:
        db: Database session
        company_id: Company UUID
        entry_date: Journal entry date
        description: Entry description
        source_module: Source module (AR, AP, BANK, etc.)
        source_id: ID of source record (invoice_id, bill_id, etc.)
        lines_list: List of line dictionaries with:
            - account_id: UUID
            - debit: Decimal or float
            - credit: Decimal or float
            - description: Optional string
    
    Returns:
        Created JournalEntry instance
    
    Raises:
        ValueError: If debits don't equal credits
    """
    # Validate that debits equal credits
    total_debit = sum(Decimal(str(line.get("debit", 0))) for line in lines_list)
    total_credit = sum(Decimal(str(line.get("credit", 0))) for line in lines_list)
    
    if total_debit != total_credit:
        raise ValueError(
            f"Journal entry is not balanced: debits={total_debit}, credits={total_credit}"
        )
    
    # Create journal entry
    journal_entry = JournalEntry(
        company_id=company_id,
        date=entry_date,
        description=description,
        source_module=source_module,
        source_id=source_id,
        status=JournalStatus.POSTED,
        posted_at=datetime.utcnow(),
    )
    db.add(journal_entry)
    db.flush()  # Get the ID
    
    # Create journal lines
    for line_data in lines_list:
        account_id = line_data["account_id"]
        
        # Verify account exists
        account = db.query(ChartOfAccount).filter(
            ChartOfAccount.id == account_id,
            ChartOfAccount.company_id == company_id
        ).first()
        
        if not account:
            raise ValueError(f"Account {account_id} not found for company {company_id}")
        
        journal_line = JournalLine(
            journal_entry_id=journal_entry.id,
            account_id=account_id,
            description=line_data.get("description"),
            debit=Decimal(str(line_data.get("debit", 0))),
            credit=Decimal(str(line_data.get("credit", 0))),
        )
        db.add(journal_line)
    
    db.commit()
    db.refresh(journal_entry)
    
    logger.info(
        f"Created journal entry {journal_entry.id} for {source_module.value} "
        f"source_id={source_id} with {len(lines_list)} lines"
    )
    
    return journal_entry


def find_account_by_type_and_name(
    db: Session,
    company_id: UUID,
    account_type: str,
    code_pattern: str | None = None,
    name_pattern: str | None = None,
    raise_on_multiple: bool = True,
) -> ChartOfAccount | None:
    """
    Find an account by type and optional code/name patterns.
    
    Args:
        db: Database session
        company_id: Company UUID
        account_type: Account type to match
        code_pattern: Optional code pattern (substring match)
        name_pattern: Optional name pattern (substring match)
        raise_on_multiple: If True, raise ValueError when multiple matches found
    
    Returns:
        ChartOfAccount or None
    
    Raises:
        ValueError: If multiple matches found and raise_on_multiple=True
    """
    from app.domain.accounting.enums import AccountType
    
    query = db.query(ChartOfAccount).filter(
        ChartOfAccount.company_id == company_id,
        ChartOfAccount.account_type == AccountType(account_type),
        ChartOfAccount.is_active == True
    )
    
    if code_pattern:
        query = query.filter(ChartOfAccount.code.ilike(f"%{code_pattern}%"))
    
    if name_pattern:
        query = query.filter(ChartOfAccount.name.ilike(f"%{name_pattern}%"))
    
    results = query.all()
    
    if len(results) > 1 and raise_on_multiple:
        raise ValueError(
            f"Multiple accounts found for type={account_type}, "
            f"code_pattern={code_pattern}, name_pattern={name_pattern}. "
            f"Found {len(results)} accounts: {[a.code for a in results]}"
        )
    
    return results[0] if results else None
