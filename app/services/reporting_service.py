"""Reporting service for generating accounting reports."""

import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.accounting import (
    ChartOfAccount,
    JournalEntry,
    JournalLine,
)
from app.domain.accounting.enums import (
    AccountType,
    JournalStatus,
)

logger = logging.getLogger(__name__)


def get_profit_and_loss(
    db: Session,
    company_id: UUID,
    date_from: date,
    date_to: date,
    granularity: str = "monthly",
) -> Dict[str, Any]:
    """
    Generate Profit & Loss report.
    
    Args:
        db: Database session
        company_id: Company UUID
        date_from: Start date
        date_to: End date
        granularity: "monthly", "quarterly", or "yearly"
    
    Returns:
        Dict with periods, accounts, and totals
    """
    # Build period extraction based on granularity
    if granularity == "monthly":
        period_expr = func.to_char(JournalEntry.date, "YYYY-MM")
    elif granularity == "quarterly":
        # PostgreSQL: Extract quarter and format as YYYY-Qn
        period_expr = func.concat(
            func.to_char(JournalEntry.date, "YYYY"),
            "-Q",
            func.to_char(JournalEntry.date, "Q")
        )
    elif granularity == "yearly":
        period_expr = func.to_char(JournalEntry.date, "YYYY")
    else:
        period_expr = func.to_char(JournalEntry.date, "YYYY-MM")
    
    # Query journal lines with joins
    query = (
        db.query(
            ChartOfAccount.id.label("account_id"),
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.account_type,
            period_expr.label("period"),
            func.sum(
                case(
                    (ChartOfAccount.account_type == AccountType.REVENUE, JournalLine.credit - JournalLine.debit),
                    (ChartOfAccount.account_type == AccountType.EXPENSE, JournalLine.debit - JournalLine.credit),
                    else_=0
                )
            ).label("net_amount")
        )
        .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .filter(
            JournalEntry.company_id == company_id,
            JournalEntry.date >= date_from,
            JournalEntry.date <= date_to,
            JournalEntry.status == JournalStatus.POSTED,
            ChartOfAccount.account_type.in_([AccountType.REVENUE, AccountType.EXPENSE])
        )
        .group_by(
            ChartOfAccount.id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.account_type,
            period_expr
        )
        .order_by(ChartOfAccount.code, period_expr)
    )
    
    results = query.all()
    
    # Organize data by account
    accounts_dict: Dict[str, Dict[str, Any]] = {}
    periods_set = set()
    
    for row in results:
        account_key = str(row.account_id)
        period = row.period
        
        periods_set.add(period)
        
        if account_key not in accounts_dict:
            accounts_dict[account_key] = {
                "account_id": str(row.account_id),
                "code": row.code,
                "name": row.name,
                "type": row.account_type.value.upper(),
                "period_amounts": {},
                "total": Decimal("0.00")
            }
        
        net_amount = Decimal(str(row.net_amount or 0))
        accounts_dict[account_key]["period_amounts"][period] = float(net_amount)
        accounts_dict[account_key]["total"] += net_amount
    
    # Convert to list and format totals
    accounts = []
    total_revenue = Decimal("0.00")
    total_expenses = Decimal("0.00")
    
    for acc in accounts_dict.values():
        acc["total"] = float(acc["total"])
        accounts.append(acc)
        
        if acc["type"] == "REVENUE":
            total_revenue += Decimal(str(acc["total"]))
        elif acc["type"] == "EXPENSE":
            total_expenses += Decimal(str(acc["total"]))
    
    # Sort periods
    periods = sorted(list(periods_set))
    
    net_profit = total_revenue - total_expenses
    
    return {
        "periods": periods,
        "accounts": accounts,
        "totals": {
            "revenue": float(total_revenue),
            "expenses": float(total_expenses),
            "net_profit": float(net_profit)
        }
    }


def get_balance_sheet(
    db: Session,
    company_id: UUID,
    as_of: date,
) -> Dict[str, Any]:
    """
    Generate Balance Sheet report.
    
    Args:
        db: Database session
        company_id: Company UUID
        as_of: As-of date
    
    Returns:
        Dict with sections (Assets, Liabilities, Equity) and totals
    """
    # Query all accounts with their balances
    query = (
        db.query(
            ChartOfAccount.id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.account_type,
            func.sum(
                case(
                    (
                        ChartOfAccount.account_type.in_([AccountType.ASSET, AccountType.EXPENSE]),
                        JournalLine.debit - JournalLine.credit
                    ),
                    (
                        ChartOfAccount.account_type.in_([AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE]),
                        JournalLine.credit - JournalLine.debit
                    ),
                    else_=0
                )
            ).label("balance")
        )
        .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .filter(
            JournalEntry.company_id == company_id,
            JournalEntry.date <= as_of,
            JournalEntry.status == JournalStatus.POSTED
        )
        .group_by(
            ChartOfAccount.id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.account_type
        )
        .having(func.sum(
            case(
                (
                    ChartOfAccount.account_type.in_([AccountType.ASSET, AccountType.EXPENSE]),
                    JournalLine.debit - JournalLine.credit
                ),
                (
                    ChartOfAccount.account_type.in_([AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE]),
                    JournalLine.credit - JournalLine.debit
                ),
                else_=0
            )
        ) != 0)  # Only include accounts with non-zero balances
        .order_by(ChartOfAccount.code)
    )
    
    results = query.all()
    
    # Organize by section
    assets = []
    liabilities = []
    equity = []
    
    total_assets = Decimal("0.00")
    total_liabilities = Decimal("0.00")
    total_equity = Decimal("0.00")
    
    for row in results:
        balance = Decimal(str(row.balance or 0))
        
        account_data = {
            "code": row.code,
            "name": row.name,
            "balance": float(balance)
        }
        
        if row.account_type == AccountType.ASSET:
            assets.append(account_data)
            total_assets += balance
        elif row.account_type == AccountType.LIABILITY:
            liabilities.append(account_data)
            total_liabilities += balance
        elif row.account_type == AccountType.EQUITY:
            equity.append(account_data)
            total_equity += balance
    
    sections = []
    
    if assets:
        sections.append({
            "name": "Assets",
            "total": float(total_assets),
            "accounts": assets
        })
    
    if liabilities:
        sections.append({
            "name": "Liabilities",
            "total": float(total_liabilities),
            "accounts": liabilities
        })
    
    if equity:
        sections.append({
            "name": "Equity",
            "total": float(total_equity),
            "accounts": equity
        })
    
    liabilities_plus_equity = total_liabilities + total_equity
    
    return {
        "as_of": as_of.isoformat(),
        "sections": sections,
        "check": {
            "assets": float(total_assets),
            "liabilities_plus_equity": float(liabilities_plus_equity)
        }
    }


def classify_account_for_cash_flow(account: ChartOfAccount) -> str:
    """
    Classify account for cash flow statement categorization.
    
    Args:
        account: ChartOfAccount instance
    
    Returns:
        "OPERATING", "INVESTING", or "FINANCING"
    """
    if account.account_type in [AccountType.REVENUE, AccountType.EXPENSE]:
        return "OPERATING"
    elif account.account_type == AccountType.ASSET and not account.is_cash:
        # Fixed assets, inventory, etc. → Investing
        return "INVESTING"
    elif account.account_type in [AccountType.LIABILITY, AccountType.EQUITY]:
        # Loans, equity → Financing
        return "FINANCING"
    else:
        # Default to operating for cash accounts and others
        return "OPERATING"


def get_cash_flow(
    db: Session,
    company_id: UUID,
    date_from: date,
    date_to: date,
) -> Dict[str, Any]:
    """
    Generate Cash Flow report.
    
    Args:
        db: Database session
        company_id: Company UUID
        date_from: Start date
        date_to: End date
    
    Returns:
        Dict with cash flow breakdown by category
    """
    # Get opening cash balance (before date_from)
    opening_query = (
        db.query(
            func.sum(JournalLine.debit - JournalLine.credit).label("opening_balance")
        )
        .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .filter(
            JournalEntry.company_id == company_id,
            JournalEntry.date < date_from,
            JournalEntry.status == JournalStatus.POSTED,
            ChartOfAccount.is_cash == True
        )
    )
    opening_result = opening_query.scalar()
    opening_cash = Decimal(str(opening_result or 0))
    
    # Get all journal entries in period that affect cash accounts
    # We need to find entries where at least one line is a cash account
    # and categorize based on the other accounts in the same entry
    
    # First, get all journal entries in period
    entries_in_period = (
        db.query(JournalEntry.id)
        .filter(
            JournalEntry.company_id == company_id,
            JournalEntry.date >= date_from,
            JournalEntry.date <= date_to,
            JournalEntry.status == JournalStatus.POSTED
        )
        .subquery()
    )
    
    # Get all lines for these entries
    all_lines_query = (
        db.query(
            JournalEntry.id.label("entry_id"),
            JournalLine.account_id,
            ChartOfAccount.account_type,
            ChartOfAccount.is_cash,
            JournalLine.debit,
            JournalLine.credit
        )
        .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .filter(JournalEntry.id.in_(select(entries_in_period.c.id)))
    )
    
    all_lines = all_lines_query.all()
    
    # Group by entry_id
    entries_dict: Dict[UUID, List[Any]] = {}
    for line in all_lines:
        entry_id = line.entry_id
        if entry_id not in entries_dict:
            entries_dict[entry_id] = []
        entries_dict[entry_id].append(line)
    
    # Categorize cash flows
    operating_inflows = Decimal("0.00")
    operating_outflows = Decimal("0.00")
    investing_inflows = Decimal("0.00")
    investing_outflows = Decimal("0.00")
    financing_inflows = Decimal("0.00")
    financing_outflows = Decimal("0.00")
    
    for entry_id, lines in entries_dict.items():
        # Find cash lines in this entry
        cash_lines = [l for l in lines if l.is_cash]
        non_cash_lines = [l for l in lines if not l.is_cash]
        
        if not cash_lines:
            continue  # Skip entries that don't affect cash
        
        # Calculate net cash change for this entry
        cash_change = sum(Decimal(str(l.debit)) - Decimal(str(l.credit)) for l in cash_lines)
        
        if cash_change == 0:
            continue
        
        # Categorize based on non-cash accounts in the entry
        # If no non-cash lines, default to operating
        if not non_cash_lines:
            category = "OPERATING"
        else:
            # Use the first non-cash account to determine category
            first_non_cash = non_cash_lines[0]
            # Get the account to classify
            account = db.query(ChartOfAccount).filter(
                ChartOfAccount.id == first_non_cash.account_id
            ).first()
            
            if account:
                category = classify_account_for_cash_flow(account)
            else:
                category = "OPERATING"
        
        # Categorize the cash flow
        if cash_change > 0:  # Cash inflow
            if category == "OPERATING":
                operating_inflows += cash_change
            elif category == "INVESTING":
                investing_inflows += cash_change
            elif category == "FINANCING":
                financing_inflows += cash_change
        else:  # Cash outflow
            abs_change = abs(cash_change)
            if category == "OPERATING":
                operating_outflows += abs_change
            elif category == "INVESTING":
                investing_outflows += abs_change
            elif category == "FINANCING":
                financing_outflows += abs_change
    
    # Calculate net changes
    operating_net = operating_inflows - operating_outflows
    investing_net = investing_inflows - investing_outflows
    financing_net = financing_inflows - financing_outflows
    
    net_change = operating_net + investing_net + financing_net
    closing_cash = opening_cash + net_change
    
    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat()
        },
        "opening_cash": float(opening_cash),
        "closing_cash": float(closing_cash),
        "categories": {
            "OPERATING": {
                "inflows": float(operating_inflows),
                "outflows": float(operating_outflows),
                "net": float(operating_net)
            },
            "INVESTING": {
                "inflows": float(investing_inflows),
                "outflows": float(investing_outflows),
                "net": float(investing_net)
            },
            "FINANCING": {
                "inflows": float(financing_inflows),
                "outflows": float(financing_outflows),
                "net": float(financing_net)
            }
        },
        "net_change_in_cash": float(net_change)
    }

