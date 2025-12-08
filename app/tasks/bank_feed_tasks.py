"""Celery tasks for bank feed processing."""

import logging
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.bank_feed import BankFile, BankTransaction, ClassificationStatus
from app.services.bank_feed.ai_classifier import classify_transactions_batch
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


@celery_app.task(name="bank_feed.classify_file", bind=True, max_retries=3)
def classify_bank_file(self, file_id: int, use_ai: bool = False):
    """
    Classify all transactions in a bank file.
    
    Args:
        file_id: Bank file ID
        use_ai: Whether to use AI classification (if OpenAI is configured)
    """
    db = SessionLocal()
    try:
        # Load bank file
        bank_file = db.query(BankFile).filter(BankFile.id == file_id).first()
        if not bank_file:
            logger.error(f"Bank file {file_id} not found")
            return {"status": "error", "message": f"File {file_id} not found"}
        
        # Mark as IN_PROGRESS
        bank_file.classification_status = ClassificationStatus.IN_PROGRESS
        bank_file.classification_progress = 0
        bank_file.last_classification_error = None
        db.commit()
        
        # Get all transactions for this file
        transactions = db.query(BankTransaction).filter(
            BankTransaction.bank_file_id == file_id
        ).all()
        
        if not transactions:
            logger.warning(f"No transactions found for file {file_id}")
            bank_file.classification_status = ClassificationStatus.DONE
            bank_file.classification_progress = 100
            db.commit()
            return {"status": "success", "message": "No transactions to classify"}
        
        total_transactions = len(transactions)
        transaction_ids = [txn.id for txn in transactions]
        
        logger.info(f"Classifying {total_transactions} transactions for file {file_id}")
        
        # Process in batches
        batch_size = 200
        processed = 0
        
        for i in range(0, total_transactions, batch_size):
            batch_ids = transaction_ids[i:i + batch_size]
            
            try:
                # Classify batch
                classify_transactions_batch(
                    db=db,
                    transaction_ids=batch_ids,
                    use_ai=use_ai,
                    chunk_size=100,
                )
                
                processed = min(i + batch_size, total_transactions)
                progress = int((processed / total_transactions) * 100)
                
                # Update progress
                bank_file.classification_progress = progress
                db.commit()
                
                logger.info(f"File {file_id}: Classified {processed}/{total_transactions} ({progress}%)")
                
            except Exception as e:
                logger.error(f"Error classifying batch for file {file_id}: {str(e)}")
                db.rollback()
                raise
        
        # Mark as DONE
        bank_file.classification_status = ClassificationStatus.DONE
        bank_file.classification_progress = 100
        db.commit()
        
        logger.info(f"Completed classification for file {file_id}")
        
        # Create notification (optional)
        try:
            notification_service = NotificationService(db)
            notification_service.create_notification(
                notification_type="BANK_FEED_CLASSIFIED",
                title="Bank Feed Classification Complete",
                message=f"Bank feed file '{bank_file.original_filename}' classification completed",
                user_id=None,  # Could be bank_file.uploaded_by if available
                metadata={
                    "file_id": file_id,
                    "filename": bank_file.original_filename,
                    "total_transactions": total_transactions,
                }
            )
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to create notification for file {file_id}: {str(e)}")
            # Don't fail the task if notification fails
        
        return {
            "status": "success",
            "file_id": file_id,
            "total_transactions": total_transactions,
        }
    
    except Exception as e:
        logger.error(f"Error classifying file {file_id}: {str(e)}")
        
        # Mark as FAILED
        try:
            bank_file = db.query(BankFile).filter(BankFile.id == file_id).first()
            if bank_file:
                bank_file.classification_status = ClassificationStatus.FAILED
                bank_file.last_classification_error = str(e)
                db.commit()
        except Exception as e2:
            logger.error(f"Error updating file status: {str(e2)}")
        
        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        
        return {
            "status": "error",
            "message": str(e),
            "file_id": file_id,
        }
    
    finally:
        db.close()

