import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.models.document import DocumentType, DocumentDestination
from .field_parser import InvoiceFieldParser, ParsedInvoiceFields

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of document classification."""
    document_type: DocumentType
    destination: DocumentDestination
    confidence: float  # 0.0 to 1.0
    parsed_fields: ParsedInvoiceFields
    needs_review: bool = False
    classification_reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class DocumentClassifier:
    """
    Classifies documents as Invoice, Receipt, or Unknown.
    Routes them to Account Payable or Account Receivable.
    
    Uses rule-based classification with confidence scoring:
    - Keyword matching
    - Field presence analysis
    - Pattern recognition
    """

    # Keywords that strongly indicate document type
    INVOICE_KEYWORDS = {
        "strong": ["invoice", "inv#", "invoice number", "bill to", "remit to", "amount due"],
        "medium": ["due date", "payment terms", "net 30", "net 60", "balance due"],
        "weak": ["qty", "quantity", "unit price", "description", "total"],
    }

    RECEIPT_KEYWORDS = {
        "strong": ["receipt", "paid", "payment received", "thank you for your payment"],
        "medium": ["payment confirmation", "confirmation number", "transaction id"],
        "weak": ["order complete", "delivered", "shipped"],
    }

    # Keywords indicating direction (AP vs AR)
    AP_KEYWORDS = ["bill to", "ship to", "sold to", "remit payment to", "pay to"]
    AR_KEYWORDS = ["sold by", "from:", "our reference", "your account"]

    def __init__(self, confidence_threshold: float = 0.75):
        """
        Initialize classifier.
        
        Args:
            confidence_threshold: Minimum confidence for auto-classification
        """
        self.confidence_threshold = confidence_threshold
        self.field_parser = InvoiceFieldParser()

    def classify(self, text: str, source_email: Optional[str] = None) -> ClassificationResult:
        """
        Classify a document based on its text content.
        
        Args:
            text: Extracted text from document
            source_email: Email address the document came from (for routing hints)
        
        Returns:
            ClassificationResult with type, destination, and confidence
        """
        text_lower = text.lower()
        
        # Parse fields
        parsed_fields = self.field_parser.parse(text)
        
        # Calculate scores for each type
        invoice_score = self._calculate_type_score(text_lower, "invoice", parsed_fields)
        receipt_score = self._calculate_type_score(text_lower, "receipt", parsed_fields)
        
        # Determine document type
        document_type, type_confidence, reasons = self._determine_type(
            invoice_score, receipt_score, parsed_fields
        )
        
        # Determine destination (AP vs AR)
        destination, dest_confidence, dest_reasons = self._determine_destination(
            text_lower, document_type, source_email
        )
        reasons.extend(dest_reasons)
        
        # Calculate overall confidence
        overall_confidence = (type_confidence + dest_confidence) / 2
        
        # Determine if review is needed
        needs_review = overall_confidence < self.confidence_threshold
        
        # Generate tags
        tags = self._generate_tags(document_type, needs_review, parsed_fields)
        
        return ClassificationResult(
            document_type=document_type,
            destination=destination,
            confidence=overall_confidence,
            parsed_fields=parsed_fields,
            needs_review=needs_review,
            classification_reasons=reasons,
            tags=tags,
        )

    def _calculate_type_score(
        self,
        text_lower: str,
        doc_type: str,
        parsed_fields: ParsedInvoiceFields,
    ) -> float:
        """Calculate confidence score for a document type."""
        score = 0.0
        keywords = self.INVOICE_KEYWORDS if doc_type == "invoice" else self.RECEIPT_KEYWORDS
        
        # Strong keywords: +0.4 each (max 0.8)
        strong_matches = sum(1 for kw in keywords["strong"] if kw in text_lower)
        score += min(strong_matches * 0.4, 0.8)
        
        # Medium keywords: +0.15 each (max 0.3)
        medium_matches = sum(1 for kw in keywords["medium"] if kw in text_lower)
        score += min(medium_matches * 0.15, 0.3)
        
        # Weak keywords: +0.05 each (max 0.15)
        weak_matches = sum(1 for kw in keywords["weak"] if kw in text_lower)
        score += min(weak_matches * 0.05, 0.15)
        
        # Field-based scoring
        if doc_type == "invoice":
            if parsed_fields.invoice_number:
                score += 0.2
            if parsed_fields.due_date:
                score += 0.15
            if parsed_fields.total_amount:
                score += 0.1
            if parsed_fields.vendor_name:
                score += 0.1
        else:  # receipt
            if "paid" in text_lower or "payment received" in text_lower:
                score += 0.25
            if parsed_fields.total_amount:
                score += 0.1
        
        return min(score, 1.0)

    def _determine_type(
        self,
        invoice_score: float,
        receipt_score: float,
        parsed_fields: ParsedInvoiceFields,
    ) -> tuple[DocumentType, float, list[str]]:
        """Determine document type from scores."""
        reasons = []
        
        # Clear winner
        if invoice_score > receipt_score + 0.2:
            reasons.append(f"Invoice score ({invoice_score:.2f}) significantly higher than receipt ({receipt_score:.2f})")
            return DocumentType.INVOICE, invoice_score, reasons
        
        if receipt_score > invoice_score + 0.2:
            reasons.append(f"Receipt score ({receipt_score:.2f}) significantly higher than invoice ({invoice_score:.2f})")
            return DocumentType.RECEIPT, receipt_score, reasons
        
        # Close scores - use field presence as tiebreaker
        if parsed_fields.invoice_number and invoice_score >= receipt_score:
            reasons.append("Invoice number present, classified as invoice")
            return DocumentType.INVOICE, invoice_score, reasons
        
        if parsed_fields.total_amount and receipt_score >= invoice_score:
            reasons.append("Payment indicators present, classified as receipt")
            return DocumentType.RECEIPT, receipt_score, reasons
        
        # Can't determine
        reasons.append("Unable to confidently determine document type")
        return DocumentType.UNKNOWN, max(invoice_score, receipt_score) * 0.5, reasons

    def _determine_destination(
        self,
        text_lower: str,
        document_type: DocumentType,
        source_email: Optional[str],
    ) -> tuple[DocumentDestination, float, list[str]]:
        """Determine whether document goes to AP or AR."""
        reasons = []
        
        # Count AP vs AR keywords
        ap_score = sum(1 for kw in self.AP_KEYWORDS if kw in text_lower)
        ar_score = sum(1 for kw in self.AR_KEYWORDS if kw in text_lower)
        
        # Email-based hints
        if source_email:
            email_lower = source_email.lower()
            # If from a vendor domain, likely AP
            vendor_indicators = ["invoice", "billing", "accounts", "ar@", "receivables"]
            for indicator in vendor_indicators:
                if indicator in email_lower:
                    ap_score += 2
                    reasons.append(f"Email address suggests vendor: {source_email}")
                    break
        
        # Default routing based on document type
        if document_type == DocumentType.INVOICE:
            # Invoices typically go to AP (we received an invoice to pay)
            ap_score += 1
            reasons.append("Invoices default to Account Payable")
        elif document_type == DocumentType.RECEIPT:
            # Receipts could go either way - payment we made (AP) or received (AR)
            if "payment received" in text_lower or "thank you for your payment" in text_lower:
                ar_score += 2
                reasons.append("Payment receipt indicates Account Receivable")
            else:
                ap_score += 1
                reasons.append("Payment confirmation defaults to Account Payable")
        
        # Calculate confidence
        total = ap_score + ar_score
        if total == 0:
            reasons.append("No clear destination indicators")
            return DocumentDestination.UNASSIGNED, 0.5, reasons
        
        if ap_score > ar_score:
            confidence = ap_score / (total + 1)
            reasons.append(f"Routing to Account Payable (score: {ap_score} vs {ar_score})")
            return DocumentDestination.ACCOUNT_PAYABLE, min(confidence, 1.0), reasons
        elif ar_score > ap_score:
            confidence = ar_score / (total + 1)
            reasons.append(f"Routing to Account Receivable (score: {ar_score} vs {ap_score})")
            return DocumentDestination.ACCOUNT_RECEIVABLE, min(confidence, 1.0), reasons
        else:
            reasons.append("Equal AP/AR indicators, defaulting to AP")
            return DocumentDestination.ACCOUNT_PAYABLE, 0.5, reasons

    def _generate_tags(
        self,
        document_type: DocumentType,
        needs_review: bool,
        parsed_fields: ParsedInvoiceFields,
    ) -> list[str]:
        """Generate tags for the document."""
        tags = []
        
        # Type tag
        if document_type == DocumentType.INVOICE:
            tags.append("invoice")
        elif document_type == DocumentType.RECEIPT:
            tags.append("receipt")
        
        # Review tag
        if needs_review:
            tags.append("needs_review")
        
        # Amount-based tags
        if parsed_fields.total_amount:
            if parsed_fields.total_amount >= 10000:
                tags.append("high_value")
            elif parsed_fields.total_amount >= 1000:
                tags.append("medium_value")
        
        # Date-based tags
        if parsed_fields.due_date:
            from datetime import datetime
            days_until_due = (parsed_fields.due_date - datetime.now()).days
            if days_until_due <= 7:
                tags.append("urgent")
            elif days_until_due <= 14:
                tags.append("due_soon")
        
        return tags

