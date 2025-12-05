import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LineItem:
    """Represents a line item from an invoice."""
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None


@dataclass
class ParsedInvoiceFields:
    """Parsed fields from an invoice/receipt."""
    # Identification
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_email: Optional[str] = None
    vendor_phone: Optional[str] = None
    
    # Document info
    invoice_number: Optional[str] = None
    po_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    
    # Amounts
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    tax_rate: Optional[float] = None
    discount: Optional[float] = None
    total_amount: Optional[float] = None
    currency: str = "USD"
    
    # Payment
    payment_terms: Optional[str] = None
    bank_account: Optional[str] = None
    payment_method: Optional[str] = None
    
    # Line items
    line_items: list[LineItem] = field(default_factory=list)
    
    # Metadata
    raw_text: str = ""
    confidence_scores: dict = field(default_factory=dict)


class InvoiceFieldParser:
    """
    Parses invoice/receipt fields from extracted text.
    
    Uses regex patterns and heuristics to extract:
    - Vendor information
    - Invoice numbers and dates
    - Amounts and totals
    - Line items
    """

    # Regex patterns for field extraction
    PATTERNS = {
        "invoice_number": [
            r"invoice\s*#?\s*:?\s*([A-Z0-9\-]+)",
            r"inv\s*#?\s*:?\s*([A-Z0-9\-]+)",
            r"bill\s*#?\s*:?\s*([A-Z0-9\-]+)",
            r"receipt\s*#?\s*:?\s*([A-Z0-9\-]+)",
            r"#\s*([A-Z]{2,}[\-]?\d+)",
        ],
        "po_number": [
            r"p\.?o\.?\s*#?\s*:?\s*([A-Z0-9\-]+)",
            r"purchase\s*order\s*#?\s*:?\s*([A-Z0-9\-]+)",
        ],
        "date": [
            r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})",
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})",
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
        ],
        "amount": [
            r"\$\s*([\d,]+\.?\d*)",
            r"USD\s*([\d,]+\.?\d*)",
            r"([\d,]+\.?\d*)\s*USD",
            r"total:?\s*\$?\s*([\d,]+\.?\d*)",
        ],
        "tax": [
            r"tax:?\s*\$?\s*([\d,]+\.?\d*)",
            r"vat:?\s*\$?\s*([\d,]+\.?\d*)",
            r"gst:?\s*\$?\s*([\d,]+\.?\d*)",
            r"(\d+\.?\d*)%\s*tax",
        ],
        "email": [
            r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        ],
        "phone": [
            r"(\+?1?[\-\.\s]?\(?\d{3}\)?[\-\.\s]?\d{3}[\-\.\s]?\d{4})",
            r"tel:?\s*(\+?[\d\-\.\s\(\)]+)",
            r"phone:?\s*(\+?[\d\-\.\s\(\)]+)",
        ],
    }

    # Keywords for classification
    INVOICE_KEYWORDS = [
        "invoice", "inv", "bill", "billing", "statement",
        "amount due", "payment due", "balance due",
        "remit to", "pay to", "wire transfer",
    ]
    
    RECEIPT_KEYWORDS = [
        "receipt", "paid", "payment received", "thank you for your payment",
        "payment confirmation", "transaction", "confirmation number",
        "order complete", "purchase complete",
    ]

    def parse(self, text: str) -> ParsedInvoiceFields:
        """
        Parse invoice fields from text.
        
        Args:
            text: Extracted text from document
        
        Returns:
            ParsedInvoiceFields with extracted information
        """
        result = ParsedInvoiceFields(raw_text=text)
        text_lower = text.lower()
        
        # Extract invoice number
        result.invoice_number = self._extract_pattern(text, "invoice_number")
        result.confidence_scores["invoice_number"] = 0.9 if result.invoice_number else 0.0
        
        # Extract PO number
        result.po_number = self._extract_pattern(text, "po_number")
        
        # Extract dates
        dates = self._extract_all_dates(text)
        if dates:
            result.invoice_date = dates[0]
            if len(dates) > 1:
                result.due_date = dates[-1]
        result.confidence_scores["dates"] = 0.8 if dates else 0.0
        
        # Extract amounts
        amounts = self._extract_all_amounts(text)
        if amounts:
            result.total_amount = max(amounts)  # Usually the largest is the total
            result.confidence_scores["total_amount"] = 0.85
        
        # Extract tax
        tax_match = self._extract_pattern(text_lower, "tax")
        if tax_match:
            try:
                result.tax_amount = float(tax_match.replace(",", ""))
            except ValueError:
                pass
        
        # Extract email
        result.vendor_email = self._extract_pattern(text, "email")
        
        # Extract phone
        result.vendor_phone = self._extract_pattern(text, "phone")
        
        # Extract vendor name (heuristic: first line that looks like a company name)
        result.vendor_name = self._extract_vendor_name(text)
        result.confidence_scores["vendor_name"] = 0.7 if result.vendor_name else 0.0
        
        # Extract line items
        result.line_items = self._extract_line_items(text)
        
        # Detect currency
        result.currency = self._detect_currency(text)
        
        return result

    def _extract_pattern(self, text: str, pattern_name: str) -> Optional[str]:
        """Extract first match for a pattern group."""
        patterns = self.PATTERNS.get(pattern_name, [])
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_all_dates(self, text: str) -> list[datetime]:
        """Extract all dates from text."""
        dates = []
        for pattern in self.PATTERNS["date"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                parsed = self._parse_date(match)
                if parsed and parsed not in dates:
                    dates.append(parsed)
        return sorted(dates)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse a date string into datetime."""
        formats = [
            "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
            "%m-%d-%Y", "%d-%m-%Y", "%Y-%m-%d",
            "%m/%d/%y", "%d/%m/%y",
            "%B %d, %Y", "%d %B %Y",
            "%b %d, %Y", "%d %b %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None

    def _extract_all_amounts(self, text: str) -> list[float]:
        """Extract all monetary amounts from text."""
        amounts = []
        for pattern in self.PATTERNS["amount"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    amount = float(match.replace(",", ""))
                    if amount > 0:
                        amounts.append(amount)
                except ValueError:
                    continue
        return sorted(set(amounts))

    def _extract_vendor_name(self, text: str) -> Optional[str]:
        """Extract vendor name using heuristics."""
        lines = text.split("\n")
        
        # Common patterns for vendor names
        vendor_patterns = [
            r"^from:?\s*(.+)",
            r"^bill from:?\s*(.+)",
            r"^seller:?\s*(.+)",
            r"^vendor:?\s*(.+)",
        ]
        
        for line in lines[:10]:  # Check first 10 lines
            line = line.strip()
            if not line or len(line) < 3:
                continue
            
            # Try patterns
            for pattern in vendor_patterns:
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
            
            # Heuristic: First non-trivial line that looks like a company name
            # (not a date, not just numbers, not common header words)
            if self._looks_like_company_name(line):
                return line
        
        return None

    def _looks_like_company_name(self, text: str) -> bool:
        """Check if text looks like a company name."""
        # Reject if too short or too long
        if len(text) < 3 or len(text) > 100:
            return False
        
        # Reject if just numbers or date
        if re.match(r"^[\d\s\-\/\.]+$", text):
            return False
        
        # Reject common header words
        skip_words = [
            "invoice", "receipt", "bill", "statement", "page",
            "date", "total", "amount", "tax", "subtotal",
        ]
        if text.lower() in skip_words:
            return False
        
        # Accept if contains company suffixes
        company_suffixes = ["inc", "llc", "ltd", "corp", "co", "company", "group"]
        for suffix in company_suffixes:
            if suffix in text.lower():
                return True
        
        # Accept if starts with capital and has reasonable structure
        if text[0].isupper() and " " in text:
            return True
        
        return False

    def _extract_line_items(self, text: str) -> list[LineItem]:
        """Extract line items from text."""
        items = []
        
        # Pattern for line items: description followed by quantity and amount
        line_item_pattern = r"(.{10,50})\s+(\d+\.?\d*)\s+\$?\s*([\d,]+\.?\d*)"
        
        matches = re.findall(line_item_pattern, text)
        for match in matches:
            try:
                items.append(LineItem(
                    description=match[0].strip(),
                    quantity=float(match[1]) if match[1] else None,
                    total=float(match[2].replace(",", "")) if match[2] else None,
                ))
            except (ValueError, IndexError):
                continue
        
        return items

    def _detect_currency(self, text: str) -> str:
        """Detect currency from text."""
        currency_patterns = {
            "USD": [r"\$", r"USD", r"US\s*Dollar"],
            "EUR": [r"€", r"EUR", r"Euro"],
            "GBP": [r"£", r"GBP", r"Pound"],
            "INR": [r"₹", r"INR", r"Rs\.?"],
            "CAD": [r"CAD", r"C\$"],
        }
        
        for currency, patterns in currency_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return currency
        
        return "USD"  # Default

