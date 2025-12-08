"""
Mock services for testing without external dependencies.

Usage:
    Set environment variable MOCK_MODE=true to use mock services.
"""

import asyncio
from datetime import datetime
from typing import Optional
import hashlib
import uuid

from app.services.email.base import EmailAdapter, EmailMessage, EmailAttachment
from app.services.ocr.base import OCRProvider, OCRResult
from app.services.storage.s3_storage import StoredFile


# Sample mock data
MOCK_INVOICE_TEXT = """
INVOICE

Supplier Corp
123 Business Ave
New York, NY 10001

Invoice #: INV-2024-1847
Date: January 15, 2024
Due Date: February 14, 2024

Bill To:
Acme Company
456 Corporate Blvd
Los Angeles, CA 90001

Description                     Qty    Unit Price    Amount
------------------------------------------------------------
Office Supplies                  50       $9.70     $485.00
Printer Cartridges              10      $32.00     $320.00
Computer Peripherals             5     $250.00   $1,250.00
------------------------------------------------------------
                              Subtotal:          $2,055.00
                              Tax (8%):            $164.40
                              TOTAL DUE:         $2,219.40

Payment Terms: Net 30
Please remit payment to the address above.

Thank you for your business!
"""

MOCK_RECEIPT_TEXT = """
PAYMENT RECEIPT

Receipt #: REC-2024-0892
Date: January 20, 2024

Received From: Acme Company
Amount: $2,219.40

Payment Method: Wire Transfer
Reference: WT-789012

This receipt confirms that payment has been received in full
for Invoice #INV-2024-1847.

Thank you for your payment!

Supplier Corp
Accounts Receivable
"""

MOCK_PDF_CONTENT = b"%PDF-1.4 mock pdf content for testing"
MOCK_IMAGE_CONTENT = b"\x89PNG\r\n\x1a\n mock image content"


class MockEmailAdapter(EmailAdapter):
    """Mock email adapter that returns sample emails."""

    def __init__(self):
        self._connected = False
        self._processed_uids = set()

    async def connect(self) -> None:
        await asyncio.sleep(0.1)  # Simulate connection delay
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def fetch_unread_emails(
        self,
        folder: str = "INBOX",
        limit: int = 50,
        since: Optional[datetime] = None,
    ) -> list[EmailMessage]:
        """Return mock emails."""
        if not self._connected:
            raise ConnectionError("Not connected")

        # Return sample emails
        emails = []
        
        # Invoice email
        if "mock-invoice-001" not in self._processed_uids:
            emails.append(EmailMessage(
                uid="mock-invoice-001",
                message_id="<mock-invoice-001@test.local>",
                from_address="invoices@supplier-corp.com",
                to_addresses=["ap@acme.com"],
                subject="Invoice #INV-2024-1847 - Payment Due",
                date=datetime.utcnow(),
                body_text=MOCK_INVOICE_TEXT,
                attachments=[
                    EmailAttachment(
                        filename="invoice_INV-2024-1847.pdf",
                        content_type="application/pdf",
                        content=MOCK_PDF_CONTENT,
                        size=len(MOCK_PDF_CONTENT),
                    )
                ],
            ))
        
        # Receipt email
        if "mock-receipt-002" not in self._processed_uids:
            emails.append(EmailMessage(
                uid="mock-receipt-002",
                message_id="<mock-receipt-002@test.local>",
                from_address="billing@vendor-inc.com",
                to_addresses=["ar@acme.com"],
                subject="Payment Receipt - Thank you!",
                date=datetime.utcnow(),
                body_text=MOCK_RECEIPT_TEXT,
                attachments=[
                    EmailAttachment(
                        filename="receipt_scan.jpg",
                        content_type="image/jpeg",
                        content=MOCK_IMAGE_CONTENT,
                        size=len(MOCK_IMAGE_CONTENT),
                    )
                ],
            ))

        return emails[:limit]

    async def fetch_email_by_uid(self, uid: str, folder: str = "INBOX") -> Optional[EmailMessage]:
        """Fetch a specific mock email."""
        emails = await self.fetch_unread_emails()
        for email in emails:
            if email.uid == uid:
                return email
        return None

    async def mark_as_read(self, uid: str, folder: str = "INBOX") -> bool:
        return True

    async def mark_as_processed(self, uid: str, folder: str = "INBOX") -> bool:
        self._processed_uids.add(uid)
        return True

    async def get_folders(self) -> list[str]:
        return ["INBOX", "Processed", "Archive"]

    async def health_check(self) -> bool:
        return True


class MockOCRProvider(OCRProvider):
    """Mock OCR provider that returns deterministic results."""

    async def extract_text(self, image_content: bytes, content_type: str = "image/png") -> OCRResult:
        """Return mock OCR result for images."""
        await asyncio.sleep(0.2)  # Simulate processing
        
        # Deterministic response based on content hash
        content_hash = hashlib.md5(image_content).hexdigest()
        
        if content_hash.startswith(('0', '1', '2', '3', '4')):
            text = MOCK_INVOICE_TEXT
        else:
            text = MOCK_RECEIPT_TEXT
        
        return OCRResult(
            text=text,
            confidence=0.92,
            language="en",
            word_count=len(text.split()),
            metadata={"provider": "mock", "mock_mode": True},
        )

    async def extract_text_from_pdf(self, pdf_content: bytes) -> OCRResult:
        """Return mock OCR result for PDFs."""
        await asyncio.sleep(0.3)  # Simulate processing
        
        return OCRResult(
            text=MOCK_INVOICE_TEXT,
            confidence=0.95,
            language="en",
            word_count=len(MOCK_INVOICE_TEXT.split()),
            metadata={"provider": "mock", "mock_mode": True, "page_count": 1},
        )

    async def health_check(self) -> bool:
        return True


class MockStorageService:
    """Mock S3 storage service that stores files in memory."""

    def __init__(self):
        self._storage: dict[str, tuple[bytes, dict]] = {}
        self.bucket_name = "mock-bucket"

    async def upload_file(
        self,
        content: bytes,
        original_filename: str,
        content_type: str,
        folder: str = "documents",
        metadata: Optional[dict] = None,
    ) -> StoredFile:
        """Store file in memory."""
        content_hash = hashlib.sha256(content).hexdigest()
        key = f"{folder}/{content_hash[:16]}_{uuid.uuid4().hex[:8]}"
        
        self._storage[key] = (content, metadata or {})
        
        return StoredFile(
            bucket=self.bucket_name,
            key=key,
            url=f"mock://{self.bucket_name}/{key}",
            content_hash=content_hash,
            content_type=content_type,
            size=len(content),
            original_filename=original_filename,
        )

    async def download_file(self, key: str) -> bytes:
        """Retrieve file from memory."""
        if key in self._storage:
            return self._storage[key][0]
        raise FileNotFoundError(f"File not found: {key}")

    async def delete_file(self, key: str) -> bool:
        """Delete file from memory."""
        if key in self._storage:
            del self._storage[key]
            return True
        return False

    async def get_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """Return mock presigned URL."""
        return f"mock://{self.bucket_name}/{key}?expires={expiration}"

    async def file_exists(self, key: str) -> bool:
        return key in self._storage

    async def ensure_bucket_exists(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True




