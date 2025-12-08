"""AI classification service for bank transactions."""

import logging
import json
import os
from typing import Dict, Any, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.bank_feed import BankTransaction, ClassificationStatus, TransactionType
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Get settings instance
settings = get_settings()


def classify_transaction_rule_based(txn: BankTransaction) -> Dict[str, Any]:
    """
    Rule-based classification using heuristics.
    
    This is a deterministic fallback classifier that uses transaction
    fields to categorize transactions without external AI.
    
    Args:
        txn: BankTransaction instance
    
    Returns:
        Dict with ai_category, ai_subcategory, ai_confidence, ai_ledger_hint
    """
    description_upper = (txn.description or "").upper()
    transaction_type = txn.type.value.upper() if txn.type else ""
    
    # Get raw data if available
    raw_data = txn.raw_data or {}
    details = raw_data.get("Details", "").upper() if isinstance(raw_data, dict) else ""
    type_field = raw_data.get("Type", "").upper() if isinstance(raw_data, dict) else ""
    
    # Use raw data fields if available, otherwise use model fields
    effective_type = type_field or transaction_type
    effective_details = details or transaction_type
    
    # Rule 1: Bank Fees
    if (
        effective_type == "FEE_TRANSACTION" or
        "MONTHLY SERVICE FEE" in description_upper or
        "MAINTENANCE FEE" in description_upper or
        "OVERDRAFT FEE" in description_upper or
        "NSF FEE" in description_upper
    ):
        return {
            "ai_category": "BANK_FEE",
            "ai_subcategory": "Service Fee",
            "ai_confidence": 0.85,
            "ai_ledger_hint": "OPERATING_EXPENSE",
        }
    
    # Rule 2: Credit Card Payments
    if (
        effective_type == "ACH_DEBIT" and (
            "CAPITAL ONE" in description_upper or
            "CITI CARD" in description_upper or
            "CHASE CARD" in description_upper or
            "AMEX" in description_upper or
            "CREDIT CARD" in description_upper or
            "CARD PAYMENT" in description_upper
        )
    ):
        return {
            "ai_category": "CREDIT_CARD_PAYMENT",
            "ai_subcategory": "Credit Card Payment",
            "ai_confidence": 0.80,
            "ai_ledger_hint": "OPERATING_EXPENSE",
        }
    
    # Rule 3: Vendor Payments (e.g., BacklotCars)
    if "BACKLOTCARS" in description_upper:
        return {
            "ai_category": "VENDOR_PAYMENT",
            "ai_subcategory": "BacklotCars - Auto Purchase",
            "ai_confidence": 0.75,
            "ai_ledger_hint": "OPERATING_EXPENSE",
        }
    
    # Rule 4: Debit Card Purchases
    if effective_type == "DEBIT_CARD" or effective_type == "CARD_PURCHASE":
        return {
            "ai_category": "CARD_PURCHASE",
            "ai_subcategory": "Card Purchase",
            "ai_confidence": 0.70,
            "ai_ledger_hint": "OPERATING_EXPENSE",
        }
    
    # Rule 5: Transfers
    if effective_type == "ACCT_XFER" or "TRANSFER" in description_upper:
        if effective_details == "CREDIT" or txn.type == TransactionType.CREDIT:
            return {
                "ai_category": "TRANSFER_IN",
                "ai_subcategory": "Account Transfer In",
                "ai_confidence": 0.75,
                "ai_ledger_hint": "INTERCOMPANY",
            }
        else:
            return {
                "ai_category": "TRANSFER_OUT",
                "ai_subcategory": "Account Transfer Out",
                "ai_confidence": 0.75,
                "ai_ledger_hint": "INTERCOMPANY",
            }
    
    # Rule 6: ATM Deposits
    if "ATM DEPOSIT" in description_upper or (
        effective_type == "ATM" and txn.type == TransactionType.CREDIT
    ):
        return {
            "ai_category": "ATM_DEPOSIT",
            "ai_subcategory": "ATM Deposit",
            "ai_confidence": 0.80,
            "ai_ledger_hint": "OPERATING_REVENUE",
        }
    
    # Rule 7: ATM Withdrawals
    if "ATM WITHDRAWAL" in description_upper or (
        effective_type == "ATM" and txn.type == TransactionType.DEBIT
    ):
        return {
            "ai_category": "ATM_WITHDRAWAL",
            "ai_subcategory": "ATM Withdrawal",
            "ai_confidence": 0.80,
            "ai_ledger_hint": "OWNER_DRAW",
        }
    
    # Rule 8: Payroll/Deposits
    if (
        "PAYROLL" in description_upper or
        "DIRECT DEPOSIT" in description_upper or
        "SALARY" in description_upper
    ):
        return {
            "ai_category": "PAYROLL_DEPOSIT",
            "ai_subcategory": "Payroll Deposit",
            "ai_confidence": 0.75,
            "ai_ledger_hint": "PAYROLL",
        }
    
    # Rule 9: Tax Payments
    if (
        "IRS" in description_upper or
        "TAX" in description_upper or
        "FEDERAL TAX" in description_upper
    ):
        return {
            "ai_category": "TAX_PAYMENT",
            "ai_subcategory": "Tax Payment",
            "ai_confidence": 0.80,
            "ai_ledger_hint": "TAX",
        }
    
    # Default: Unclassified
    return {
        "ai_category": "UNCLASSIFIED",
        "ai_subcategory": None,
        "ai_confidence": 0.50,
        "ai_ledger_hint": "OPERATING_EXPENSE",
    }


def classify_transaction_ai(txn: BankTransaction) -> Dict[str, Any]:
    """
    AI-based classification using OpenAI (if configured).
    
    Falls back to rule-based classification if OpenAI is not configured.
    
    Args:
        txn: BankTransaction instance
    
    Returns:
        Dict with ai_category, ai_subcategory, ai_confidence, ai_ledger_hint
    """
    openai_api_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", None)
    
    if not openai_api_key:
        logger.debug("OpenAI API key not configured, using rule-based classification")
        return classify_transaction_rule_based(txn)
    
    try:
        import openai
        
        # Build prompt from transaction fields
        raw_data = txn.raw_data or {}
        prompt = f"""Classify this bank transaction into a category.

Transaction Details:
- Description: {txn.description}
- Amount: {txn.amount}
- Type: {txn.type.value if txn.type else 'unknown'}
- Details: {raw_data.get('Details', '')}
- Transaction Type: {raw_data.get('Type', '')}

Return a JSON object with:
{{
  "category": "BANK_FEE|CREDIT_CARD_PAYMENT|VENDOR_PAYMENT|CARD_PURCHASE|TRANSFER_IN|TRANSFER_OUT|ATM_DEPOSIT|ATM_WITHDRAWAL|PAYROLL_DEPOSIT|TAX_PAYMENT|UNCLASSIFIED",
  "subcategory": "Brief description (e.g., 'BacklotCars - Auto Purchase')",
  "ledger_hint": "OPERATING_EXPENSE|OPERATING_REVENUE|OWNER_DRAW|PAYROLL|TAX|INTERCOMPANY",
  "confidence": 0.0-1.0
}}"""

        client = openai.OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a financial transaction classifier. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=150,
        )
        
        content = response.choices[0].message.content.strip()
        # Remove markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        
        result = json.loads(content)
        
        return {
            "ai_category": result.get("category", "UNCLASSIFIED"),
            "ai_subcategory": result.get("subcategory"),
            "ai_confidence": float(result.get("confidence", 0.5)),
            "ai_ledger_hint": result.get("ledger_hint", "OPERATING_EXPENSE"),
        }
    
    except ImportError:
        logger.warning("OpenAI library not installed, using rule-based classification")
        return classify_transaction_rule_based(txn)
    except Exception as e:
        logger.error(f"Error in AI classification: {str(e)}, falling back to rule-based")
        return classify_transaction_rule_based(txn)


def classify_transactions_batch(
    db: Session,
    transaction_ids: List[int],
    use_ai: bool = False,
    chunk_size: int = 100,
) -> None:
    """
    Classify a batch of transactions.
    
    Args:
        db: Database session
        transaction_ids: List of transaction IDs to classify
        use_ai: Whether to use AI classification (if OpenAI is configured)
        chunk_size: Number of transactions to commit at once
    """
    total = len(transaction_ids)
    logger.info(f"Classifying {total} transactions (use_ai={use_ai})")
    
    for i in range(0, total, chunk_size):
        chunk = transaction_ids[i:i + chunk_size]
        
        for txn_id in chunk:
            try:
                txn = db.query(BankTransaction).filter(BankTransaction.id == txn_id).first()
                if not txn:
                    logger.warning(f"Transaction {txn_id} not found")
                    continue
                
                # Skip if already classified
                if txn.classification_status == ClassificationStatus.DONE:
                    continue
                
                # Update status to IN_PROGRESS
                txn.classification_status = ClassificationStatus.IN_PROGRESS
                
                # Classify
                if use_ai:
                    result = classify_transaction_ai(txn)
                else:
                    result = classify_transaction_rule_based(txn)
                
                # Update transaction
                txn.ai_category = result["ai_category"]
                txn.ai_subcategory = result.get("ai_subcategory")
                txn.ai_confidence = result.get("ai_confidence")
                txn.ai_ledger_hint = result.get("ai_ledger_hint")
                txn.classification_status = ClassificationStatus.DONE
                
            except Exception as e:
                logger.error(f"Error classifying transaction {txn_id}: {str(e)}")
                txn = db.query(BankTransaction).filter(BankTransaction.id == txn_id).first()
                if txn:
                    txn.classification_status = ClassificationStatus.FAILED
        
        # Commit chunk
        try:
            db.commit()
            logger.info(f"Classified {min(i + chunk_size, total)}/{total} transactions")
        except Exception as e:
            db.rollback()
            logger.error(f"Error committing classification chunk: {str(e)}")
            raise
    
    logger.info(f"Completed classification of {total} transactions")

