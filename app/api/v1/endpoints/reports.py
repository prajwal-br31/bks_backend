"""Reporting API endpoints."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.services.reporting_service import (
    get_profit_and_loss,
    get_balance_sheet,
    get_cash_flow,
)
from app.schemas.reporting import (
    PnLResponse,
    BalanceSheetResponse,
    CashFlowResponse,
)

router = APIRouter()


@router.get("/pnl", response_model=PnLResponse)
def get_pnl_report(
    company_id: UUID = Query(..., description="Company UUID"),
    date_from: date = Query(..., description="Start date"),
    date_to: date = Query(..., description="End date"),
    granularity: Literal["monthly", "quarterly", "yearly"] = Query(
        "monthly", description="Report granularity"
    ),
    db: Session = Depends(get_db),
) -> PnLResponse:
    """
    Get Profit & Loss report.
    
    Returns P&L data aggregated by period and account.
    """
    try:
        result = get_profit_and_loss(
            db=db,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
        )
        return PnLResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating P&L report: {str(e)}")


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
def get_balance_sheet_report(
    company_id: UUID = Query(..., description="Company UUID"),
    as_of: date = Query(..., description="As-of date"),
    db: Session = Depends(get_db),
) -> BalanceSheetResponse:
    """
    Get Balance Sheet report.
    
    Returns balance sheet data as of the specified date.
    """
    try:
        result = get_balance_sheet(
            db=db,
            company_id=company_id,
            as_of=as_of,
        )
        return BalanceSheetResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating Balance Sheet: {str(e)}"
        )


@router.get("/cash-flow", response_model=CashFlowResponse)
def get_cash_flow_report(
    company_id: UUID = Query(..., description="Company UUID"),
    date_from: date = Query(..., description="Start date"),
    date_to: date = Query(..., description="End date"),
    db: Session = Depends(get_db),
) -> CashFlowResponse:
    """
    Get Cash Flow report.
    
    Returns cash flow data categorized by Operating, Investing, and Financing activities.
    """
    try:
        result = get_cash_flow(
            db=db,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
        )
        return CashFlowResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating Cash Flow report: {str(e)}"
        )


