"""Bank Feed service for managing transactions and matches."""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models.bank_feed import (
    BankFile,
    BankTransaction,
    BankMatch,
    BankFeedAuditLog,
    TransactionType,
    TransactionStatus,
    MatchedEntityType,
    FileStatus,
)
from app.services.storage import S3StorageService
from .csv_parser import get_parser_for_content, ParseResult, ParsedTransaction

logger = logging.getLogger(__name__)


class BankFeedService:
    """Service for bank feed operations."""

    def __init__(self, db: Session):
        self.db = db
        self.storage = S3StorageService()

    async def process_upload(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        uploaded_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process an uploaded bank statement file.
        
        Args:
            content: File content
            filename: Original filename
            content_type: MIME type
            uploaded_by: User who uploaded
        
        Returns:
            Dict with file_id, parsed summary, and transaction IDs
        """
        # Create bank file record
        bank_file = BankFile(
            original_filename=filename,
            storage_path="",  # Will be updated after upload
            file_size=len(content),
            content_type=content_type,
            status=FileStatus.UPLOADING,
            uploaded_by=uploaded_by,
        )
        self.db.add(bank_file)
        self.db.flush()

        try:
            # Upload to S3
            await self.storage.ensure_bucket_exists()
            stored = await self.storage.upload_file(
                content=content,
                original_filename=filename,
                content_type=content_type,
                folder="bank-feeds",
                metadata={"bank_file_id": str(bank_file.id)},
            )
            
            bank_file.storage_path = stored.key
            bank_file.file_hash = stored.content_hash
            bank_file.status = FileStatus.PROCESSING
            self.db.commit()

            # Parse the file
            parser = get_parser_for_content(content)
            result = parser.parse(content, filename)

            # Update file with parse results
            bank_file.status = FileStatus.COMPLETED if not result.errors else FileStatus.FAILED
            bank_file.total_rows = result.total_rows
            bank_file.parsed_rows = result.parsed_rows
            bank_file.skipped_rows = result.skipped_rows
            bank_file.bank_name = result.bank_name
            bank_file.statement_start_date = result.statement_start
            bank_file.statement_end_date = result.statement_end
            
            if result.errors:
                bank_file.error_message = "; ".join(result.errors[:5])

            # Create transactions
            transaction_ids = []
            for txn in result.transactions:
                bank_txn = BankTransaction(
                    bank_file_id=bank_file.id,
                    date=txn.date,
                    post_date=txn.post_date,
                    description=txn.description,
                    amount=txn.amount,
                    type=TransactionType.CREDIT if txn.type == "credit" else TransactionType.DEBIT,
                    balance=txn.balance,
                    category=txn.category,
                    check_number=txn.check_number,
                    memo=txn.memo,
                    external_id=txn.external_id,
                    raw_data=txn.raw_data,
                    row_number=txn.row_number,
                    status=TransactionStatus.PENDING,
                )
                self.db.add(bank_txn)
                self.db.flush()
                transaction_ids.append(bank_txn.id)

            # Create audit log
            audit = BankFeedAuditLog(
                action="file_uploaded",
                details={
                    "filename": filename,
                    "file_size": len(content),
                    "total_rows": result.total_rows,
                    "parsed_rows": result.parsed_rows,
                    "bank_name": result.bank_name,
                },
                actor_type="user" if uploaded_by else "api",
                actor_id=uploaded_by,
                bank_file_id=bank_file.id,
            )
            self.db.add(audit)
            self.db.commit()

            return {
                "file_id": bank_file.id,
                "filename": filename,
                "status": bank_file.status.value,
                "total_rows": result.total_rows,
                "parsed_rows": result.parsed_rows,
                "skipped_rows": result.skipped_rows,
                "transaction_ids": transaction_ids,
                "bank_name": result.bank_name,
                "statement_start": result.statement_start.isoformat() if result.statement_start else None,
                "statement_end": result.statement_end.isoformat() if result.statement_end else None,
                "errors": result.errors,
                "warnings": result.warnings,
            }

        except Exception as e:
            logger.error(f"Error processing upload: {e}")
            bank_file.status = FileStatus.FAILED
            bank_file.error_message = str(e)
            self.db.commit()
            raise

    def get_transactions(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[TransactionStatus] = None,
        transaction_type: Optional[TransactionType] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
        search: Optional[str] = None,
        file_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get paginated list of bank transactions with filters.
        
        Returns:
            Dict with items, total, page info
        """
        query = self.db.query(BankTransaction)

        # Apply filters
        if status:
            query = query.filter(BankTransaction.status == status)
        
        if transaction_type:
            query = query.filter(BankTransaction.type == transaction_type)
        
        if date_from:
            query = query.filter(BankTransaction.date >= date_from)
        
        if date_to:
            query = query.filter(BankTransaction.date <= date_to)
        
        if amount_min is not None:
            query = query.filter(BankTransaction.amount >= amount_min)
        
        if amount_max is not None:
            query = query.filter(BankTransaction.amount <= amount_max)
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    BankTransaction.description.ilike(search_term),
                    BankTransaction.category.ilike(search_term),
                    BankTransaction.memo.ilike(search_term),
                )
            )
        
        if file_id:
            query = query.filter(BankTransaction.bank_file_id == file_id)

        # Get total count
        total = query.count()

        # Get paginated results
        transactions = (
            query
            .order_by(BankTransaction.date.desc(), BankTransaction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        # Build response
        items = []
        for txn in transactions:
            item = {
                "id": txn.id,
                "date": txn.date.isoformat() if txn.date else None,
                "description": txn.description,
                "amount": txn.amount,
                "type": txn.type.value,
                "balance": txn.balance,
                "status": txn.status.value,
                "category": txn.category,
                "check_number": txn.check_number,
                "bank_file_id": txn.bank_file_id,
                "matched_entity": None,
            }
            
            # Include match info if exists
            if txn.match:
                item["matched_entity"] = {
                    "type": txn.match.matched_type.value,
                    "id": txn.match.matched_id,
                    "name": txn.match.matched_name,
                    "reference": txn.match.matched_reference,
                }
            
            items.append(item)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    def create_match(
        self,
        bank_transaction_id: int,
        matched_type: str,
        matched_id: int,
        matched_by: Optional[str] = None,
        matched_name: Optional[str] = None,
        matched_reference: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a match between a bank transaction and an AP/AR/Expense.
        
        Args:
            bank_transaction_id: ID of the bank transaction
            matched_type: Type of entity (ar, ap, expense)
            matched_id: ID of the matched entity
            matched_by: User who created the match
            matched_name: Name of matched entity
            matched_reference: Reference number
            notes: Optional notes
        
        Returns:
            Dict with match details
        """
        # Get transaction
        txn = self.db.query(BankTransaction).filter(
            BankTransaction.id == bank_transaction_id
        ).first()
        
        if not txn:
            raise ValueError(f"Transaction not found: {bank_transaction_id}")
        
        if txn.match:
            raise ValueError(f"Transaction already matched: {bank_transaction_id}")

        # Create match
        match = BankMatch(
            bank_transaction_id=bank_transaction_id,
            matched_type=MatchedEntityType(matched_type),
            matched_id=matched_id,
            matched_name=matched_name,
            matched_reference=matched_reference,
            matched_by=matched_by,
            is_auto_matched=False,
            notes=notes,
        )
        self.db.add(match)

        # Update transaction status
        txn.status = TransactionStatus.MATCHED

        # Create audit log
        audit = BankFeedAuditLog(
            action="match_created",
            details={
                "matched_type": matched_type,
                "matched_id": matched_id,
                "matched_name": matched_name,
                "matched_reference": matched_reference,
            },
            actor_type="user" if matched_by else "api",
            actor_id=matched_by,
            actor_name=matched_by,
            bank_transaction_id=bank_transaction_id,
        )
        self.db.add(audit)
        self.db.commit()

        return {
            "match_id": match.id,
            "bank_transaction_id": bank_transaction_id,
            "matched_type": matched_type,
            "matched_id": matched_id,
            "matched_name": matched_name,
            "status": "matched",
        }

    async def reprocess_file(self, file_id: int) -> Dict[str, Any]:
        """
        Reprocess a previously uploaded file.
        
        Args:
            file_id: ID of the bank file to reprocess
        
        Returns:
            Dict with reprocessing results
        """
        # Get file
        bank_file = self.db.query(BankFile).filter(BankFile.id == file_id).first()
        
        if not bank_file:
            raise ValueError(f"File not found: {file_id}")

        # Download from S3
        content = await self.storage.download_file(bank_file.storage_path)

        # Update status
        bank_file.status = FileStatus.REPROCESSING
        self.db.commit()

        # Delete existing transactions (that aren't matched/reconciled)
        self.db.query(BankTransaction).filter(
            BankTransaction.bank_file_id == file_id,
            BankTransaction.status.in_([TransactionStatus.PENDING, TransactionStatus.REVIEWED]),
        ).delete()
        self.db.commit()

        # Re-parse
        parser = get_parser_for_content(content)
        result = parser.parse(content, bank_file.original_filename)

        # Update file
        bank_file.status = FileStatus.COMPLETED
        bank_file.total_rows = result.total_rows
        bank_file.parsed_rows = result.parsed_rows
        bank_file.skipped_rows = result.skipped_rows

        # Create new transactions
        transaction_ids = []
        for txn in result.transactions:
            bank_txn = BankTransaction(
                bank_file_id=bank_file.id,
                date=txn.date,
                description=txn.description,
                amount=txn.amount,
                type=TransactionType.CREDIT if txn.type == "credit" else TransactionType.DEBIT,
                balance=txn.balance,
                raw_data=txn.raw_data,
                row_number=txn.row_number,
                status=TransactionStatus.PENDING,
            )
            self.db.add(bank_txn)
            self.db.flush()
            transaction_ids.append(bank_txn.id)

        # Audit log
        audit = BankFeedAuditLog(
            action="file_reprocessed",
            details={
                "total_rows": result.total_rows,
                "parsed_rows": result.parsed_rows,
            },
            actor_type="api",
            bank_file_id=file_id,
        )
        self.db.add(audit)
        self.db.commit()

        return {
            "file_id": file_id,
            "status": "completed",
            "total_rows": result.total_rows,
            "parsed_rows": result.parsed_rows,
            "transaction_ids": transaction_ids,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for bank feed dashboard."""
        # Count by status
        status_counts = (
            self.db.query(
                BankTransaction.status,
                func.count(BankTransaction.id).label("count")
            )
            .group_by(BankTransaction.status)
            .all()
        )
        
        status_map = {s.value: 0 for s in TransactionStatus}
        for status, count in status_counts:
            status_map[status.value] = count

        # Total transactions this period (last 30 days)
        from datetime import timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        recent_count = self.db.query(BankTransaction).filter(
            BankTransaction.created_at >= thirty_days_ago
        ).count()

        # Last import
        last_file = (
            self.db.query(BankFile)
            .filter(BankFile.status == FileStatus.COMPLETED)
            .order_by(BankFile.created_at.desc())
            .first()
        )

        return {
            "imported_this_period": recent_count,
            "unmatched_count": status_map.get("pending", 0),
            "matched_count": status_map.get("matched", 0),
            "reviewed_count": status_map.get("reviewed", 0),
            "cleared_count": status_map.get("cleared", 0),
            "last_import": last_file.created_at.isoformat() if last_file else None,
            "last_import_filename": last_file.original_filename if last_file else None,
        }

