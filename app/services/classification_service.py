"""Document classification service for Invoice/Receipt detection."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
import structlog

from ..models.email_document import DocumentType, DocumentDestination

logger = structlog.get_logger()


@dataclass
class ParsedFields:
    """Extracted fields from a document."""
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    receipt_number: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    total_amount: Optional[float] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    currency: str = "USD"
    payment_method: Optional[str] = None
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    raw_matches: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ClassificationResult:
    """Result of document classification."""
    document_type: DocumentType
    destination: DocumentDestination
    confidence: float
    parsed_fields: ParsedFields
    classification_reasons: List[str] = field(default_factory=list)


class ClassificationService:
    """Service for classifying documents as Invoice/Receipt."""
    
    # Patterns for field extraction
    INVOICE_PATTERNS = [
        r'\binvoice\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'\binv\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'\binvoice\s+number\s*:?\s*([A-Z0-9\-]+)',
        r'\binvoice\s+no\.?\s*:?\s*([A-Z0-9\-]+)',
    ]
    
    RECEIPT_PATTERNS = [
        r'\breceipt\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'\breceipt\s+number\s*:?\s*([A-Z0-9\-]+)',
        r'\btransaction\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'\bconfirmation\s*#?\s*:?\s*([A-Z0-9\-]+)',
    ]
    
    AMOUNT_PATTERNS = [
        r'\btotal\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bamount\s+due\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bgrand\s+total\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bbalance\s+due\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\$\s*([\d,]+\.?\d*)',
    ]
    
    TAX_PATTERNS = [
        r'\btax\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bvat\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bgst\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        r'\bsales\s+tax\s*:?\s*\$?\s*([\d,]+\.?\d*)',
    ]
    
    DATE_PATTERNS = [
        r'\bdate\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'\binvoice\s+date\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'\b(\w+\s+\d{1,2},?\s+\d{4})',  # January 15, 2024
    ]
    
    DUE_DATE_PATTERNS = [
        r'\bdue\s+date\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'\bpayment\s+due\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        r'\bdue\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
    ]
    
    VENDOR_PATTERNS = [
        r'\bfrom\s*:?\s*([A-Za-z][A-Za-z0-9\s&,\.]+?)(?:\n|$)',
        r'\bvendor\s*:?\s*([A-Za-z][A-Za-z0-9\s&,\.]+?)(?:\n|$)',
        r'\bbill\s+from\s*:?\s*([A-Za-z][A-Za-z0-9\s&,\.]+?)(?:\n|$)',
        r'\bsupplier\s*:?\s*([A-Za-z][A-Za-z0-9\s&,\.]+?)(?:\n|$)',
    ]
    
    # Keywords for classification
    INVOICE_KEYWORDS = {
        'invoice', 'inv', 'bill', 'billing', 'invoice number', 'inv#',
        'due date', 'payment due', 'amount due', 'net 30', 'net 15',
        'remit to', 'remittance', 'purchase order', 'po#'
    }
    
    RECEIPT_KEYWORDS = {
        'receipt', 'payment received', 'paid', 'thank you for your payment',
        'payment confirmation', 'transaction', 'order confirmed',
        'payment complete', 'successfully paid', 'payment accepted'
    }
    
    STATEMENT_KEYWORDS = {
        'statement', 'account statement', 'monthly statement',
        'balance forward', 'previous balance', 'account summary'
    }
    
    def __init__(self, confidence_threshold: float = 0.75):
        self.confidence_threshold = confidence_threshold
    
    def classify(self, text: str, filename: str = "") -> ClassificationResult:
        """Classify a document based on its text content."""
        text_lower = text.lower()
        filename_lower = filename.lower()
        
        # Parse fields
        parsed_fields = self._parse_fields(text)
        
        # Calculate classification scores
        scores = {
            DocumentType.INVOICE: 0.0,
            DocumentType.RECEIPT: 0.0,
            DocumentType.STATEMENT: 0.0,
            DocumentType.UNKNOWN: 0.1,  # Base score
        }
        reasons = []
        
        # Check keywords
        invoice_matches = sum(1 for kw in self.INVOICE_KEYWORDS if kw in text_lower)
        receipt_matches = sum(1 for kw in self.RECEIPT_KEYWORDS if kw in text_lower)
        statement_matches = sum(1 for kw in self.STATEMENT_KEYWORDS if kw in text_lower)
        
        if invoice_matches > 0:
            scores[DocumentType.INVOICE] += 0.3 * min(invoice_matches / 3, 1.0)
            reasons.append(f"Found {invoice_matches} invoice keyword(s)")
        
        if receipt_matches > 0:
            scores[DocumentType.RECEIPT] += 0.3 * min(receipt_matches / 3, 1.0)
            reasons.append(f"Found {receipt_matches} receipt keyword(s)")
        
        if statement_matches > 0:
            scores[DocumentType.STATEMENT] += 0.3 * min(statement_matches / 3, 1.0)
            reasons.append(f"Found {statement_matches} statement keyword(s)")
        
        # Check parsed fields
        if parsed_fields.invoice_number:
            scores[DocumentType.INVOICE] += 0.4
            reasons.append(f"Invoice number found: {parsed_fields.invoice_number}")
        
        if parsed_fields.receipt_number:
            scores[DocumentType.RECEIPT] += 0.4
            reasons.append(f"Receipt number found: {parsed_fields.receipt_number}")
        
        if parsed_fields.due_date:
            scores[DocumentType.INVOICE] += 0.2
            reasons.append(f"Due date found: {parsed_fields.due_date}")
        
        # Check filename hints
        if 'invoice' in filename_lower:
            scores[DocumentType.INVOICE] += 0.2
            reasons.append("Filename contains 'invoice'")
        elif 'receipt' in filename_lower:
            scores[DocumentType.RECEIPT] += 0.2
            reasons.append("Filename contains 'receipt'")
        elif 'statement' in filename_lower:
            scores[DocumentType.STATEMENT] += 0.2
            reasons.append("Filename contains 'statement'")
        
        # Check for payment confirmation language
        paid_patterns = ['paid', 'payment received', 'thank you for your payment']
        if any(p in text_lower for p in paid_patterns):
            scores[DocumentType.RECEIPT] += 0.15
            reasons.append("Contains payment confirmation language")
        
        # Normalize scores
        total_score = sum(scores.values())
        if total_score > 0:
            scores = {k: v / total_score for k, v in scores.items()}
        
        # Get best classification
        best_type = max(scores, key=scores.get)
        confidence = scores[best_type]
        
        # If confidence is too low, mark as unknown
        if confidence < self.confidence_threshold:
            best_type = DocumentType.UNKNOWN
            reasons.append(f"Low confidence ({confidence:.2f}), marked for review")
        
        # Determine destination
        destination = self._determine_destination(
            best_type, 
            parsed_fields, 
            confidence
        )
        
        return ClassificationResult(
            document_type=best_type,
            destination=destination,
            confidence=confidence,
            parsed_fields=parsed_fields,
            classification_reasons=reasons
        )
    
    def _parse_fields(self, text: str) -> ParsedFields:
        """Extract structured fields from document text."""
        fields = ParsedFields()
        text_lower = text.lower()
        
        # Extract invoice number
        for pattern in self.INVOICE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.invoice_number = match.group(1).strip()
                break
        
        # Extract receipt number
        for pattern in self.RECEIPT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.receipt_number = match.group(1).strip()
                break
        
        # Extract amounts (get the largest as total)
        amounts = []
        for pattern in self.AMOUNT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    amount = float(match.replace(',', ''))
                    if amount > 0:
                        amounts.append(amount)
                except ValueError:
                    pass
        
        if amounts:
            fields.total_amount = max(amounts)
        
        # Extract tax
        for pattern in self.TAX_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    fields.tax_amount = float(match.group(1).replace(',', ''))
                    break
                except ValueError:
                    pass
        
        # Extract date
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.date = match.group(1).strip()
                break
        
        # Extract due date
        for pattern in self.DUE_DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.due_date = match.group(1).strip()
                break
        
        # Extract vendor name
        for pattern in self.VENDOR_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                vendor = match.group(1).strip()
                # Clean up vendor name
                vendor = re.sub(r'\s+', ' ', vendor)
                if len(vendor) > 2 and len(vendor) < 100:
                    fields.vendor_name = vendor
                    break
        
        # Detect currency
        if '$' in text:
            fields.currency = 'USD'
        elif '€' in text:
            fields.currency = 'EUR'
        elif '£' in text:
            fields.currency = 'GBP'
        elif '₹' in text:
            fields.currency = 'INR'
        
        return fields
    
    def _determine_destination(
        self,
        doc_type: DocumentType,
        fields: ParsedFields,
        confidence: float
    ) -> DocumentDestination:
        """Determine where to route the document."""
        # Low confidence = needs review
        if confidence < self.confidence_threshold:
            return DocumentDestination.NEEDS_REVIEW
        
        # Unknown type = needs review
        if doc_type == DocumentType.UNKNOWN:
            return DocumentDestination.NEEDS_REVIEW
        
        # Invoice = Account Payable (we owe money)
        if doc_type == DocumentType.INVOICE:
            return DocumentDestination.ACCOUNT_PAYABLE
        
        # Receipt = depends on context
        # If it's a payment receipt (we paid), it goes to AP
        # If it's a sales receipt (customer paid us), it goes to AR
        # Default to AP for receipts (payment confirmations)
        if doc_type == DocumentType.RECEIPT:
            return DocumentDestination.ACCOUNT_PAYABLE
        
        # Statement = needs review
        if doc_type == DocumentType.STATEMENT:
            return DocumentDestination.NEEDS_REVIEW
        
        return DocumentDestination.NEEDS_REVIEW
    
    def to_dict(self, parsed_fields: ParsedFields) -> dict:
        """Convert ParsedFields to dictionary for JSON storage."""
        return {
            'vendor_name': parsed_fields.vendor_name,
            'invoice_number': parsed_fields.invoice_number,
            'receipt_number': parsed_fields.receipt_number,
            'date': parsed_fields.date,
            'due_date': parsed_fields.due_date,
            'total_amount': parsed_fields.total_amount,
            'subtotal': parsed_fields.subtotal,
            'tax_amount': parsed_fields.tax_amount,
            'currency': parsed_fields.currency,
            'payment_method': parsed_fields.payment_method,
            'line_items': parsed_fields.line_items,
        }

