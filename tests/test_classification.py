"""Tests for the document classification engine."""

import pytest
from app.services.classification import DocumentClassifier, InvoiceFieldParser
from app.models.document import DocumentType, DocumentDestination


class TestInvoiceFieldParser:
    """Tests for invoice field parsing."""

    def test_parse_invoice_number(self):
        parser = InvoiceFieldParser()
        text = "Invoice #INV-2024-1847\nDate: January 15, 2024"
        result = parser.parse(text)
        
        assert result.invoice_number == "INV-2024-1847"

    def test_parse_amounts(self):
        parser = InvoiceFieldParser()
        text = """
        Subtotal: $2,055.00
        Tax: $164.40
        Total: $2,219.40
        """
        result = parser.parse(text)
        
        assert result.total_amount == 2219.40

    def test_parse_dates(self):
        parser = InvoiceFieldParser()
        text = """
        Invoice Date: 01/15/2024
        Due Date: 02/14/2024
        """
        result = parser.parse(text)
        
        assert result.invoice_date is not None
        assert result.invoice_date.month == 1
        assert result.invoice_date.day == 15

    def test_parse_vendor_name(self):
        parser = InvoiceFieldParser()
        text = """
        Supplier Corp LLC
        123 Business Ave
        Invoice #12345
        """
        result = parser.parse(text)
        
        assert result.vendor_name is not None
        assert "Supplier" in result.vendor_name

    def test_detect_currency(self):
        parser = InvoiceFieldParser()
        
        usd_text = "Total: $100.00"
        result = parser.parse(usd_text)
        assert result.currency == "USD"
        
        eur_text = "Total: €100.00"
        result = parser.parse(eur_text)
        assert result.currency == "EUR"


class TestDocumentClassifier:
    """Tests for document classification."""

    def test_classify_invoice(self):
        classifier = DocumentClassifier(confidence_threshold=0.75)
        
        text = """
        INVOICE
        Invoice #INV-2024-1847
        Bill To: Acme Corp
        Amount Due: $2,219.40
        Due Date: February 14, 2024
        Remit payment to our address.
        """
        
        result = classifier.classify(text)
        
        assert result.document_type == DocumentType.INVOICE
        assert result.confidence > 0.5
        assert "invoice" in result.tags

    def test_classify_receipt(self):
        classifier = DocumentClassifier(confidence_threshold=0.75)
        
        text = """
        RECEIPT
        Payment Received
        Thank you for your payment of $500.00
        Transaction ID: TXN-12345
        Payment Method: Credit Card
        """
        
        result = classifier.classify(text)
        
        assert result.document_type == DocumentType.RECEIPT
        assert result.confidence > 0.5
        assert "receipt" in result.tags

    def test_classify_unknown(self):
        classifier = DocumentClassifier(confidence_threshold=0.75)
        
        text = """
        Hello,
        
        Just checking in about our meeting tomorrow.
        
        Best regards,
        John
        """
        
        result = classifier.classify(text)
        
        # Low confidence or unknown type should trigger review
        assert result.needs_review or result.document_type == DocumentType.UNKNOWN

    def test_destination_routing_ap(self):
        classifier = DocumentClassifier(confidence_threshold=0.75)
        
        text = """
        INVOICE
        Bill To: Our Company
        From: Vendor Inc
        Amount Due: $1,000.00
        """
        
        result = classifier.classify(text)
        
        # Invoices typically go to AP
        assert result.destination == DocumentDestination.ACCOUNT_PAYABLE

    def test_needs_review_low_confidence(self):
        classifier = DocumentClassifier(confidence_threshold=0.9)  # High threshold
        
        text = """
        Document
        Some generic text
        Amount: $100
        """
        
        result = classifier.classify(text)
        
        # Low confidence should trigger review
        assert result.needs_review
        assert "needs_review" in result.tags

    def test_tags_generation(self):
        classifier = DocumentClassifier(confidence_threshold=0.75)
        
        text = """
        INVOICE #INV-001
        Total: $15,000.00
        Due Date: Tomorrow
        """
        
        result = classifier.classify(text)
        
        # Should have type tag and possibly high_value tag
        assert "invoice" in result.tags


class TestIntegration:
    """Integration tests for the classification pipeline."""

    def test_full_classification_pipeline(self):
        classifier = DocumentClassifier()
        
        # Realistic invoice text
        invoice_text = """
        Supplier Corp
        123 Business Avenue
        New York, NY 10001
        
        INVOICE
        
        Invoice Number: INV-2024-1847
        Invoice Date: January 15, 2024
        Due Date: February 14, 2024
        
        Bill To:
        Acme Company
        456 Corporate Blvd
        Los Angeles, CA 90001
        
        Description                     Amount
        -------------------------------------------
        Professional Services         $2,000.00
        Equipment Rental               $500.00
        -------------------------------------------
        Subtotal                      $2,500.00
        Tax (8%)                        $200.00
        -------------------------------------------
        TOTAL DUE                     $2,700.00
        
        Payment Terms: Net 30
        
        Please remit payment to the address above.
        Thank you for your business!
        """
        
        result = classifier.classify(invoice_text, source_email="invoices@supplier-corp.com")
        
        # Check classification
        assert result.document_type == DocumentType.INVOICE
        assert result.destination == DocumentDestination.ACCOUNT_PAYABLE
        
        # Check parsed fields
        assert result.parsed_fields.invoice_number == "INV-2024-1847"
        assert result.parsed_fields.total_amount == 2700.00
        assert result.parsed_fields.vendor_name is not None





