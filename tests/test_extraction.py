"""Tests for attachment extraction."""

import pytest
from app.services.extraction import AttachmentExtractor, ContentExtractor


class TestAttachmentExtractor:
    """Tests for attachment extraction."""

    def test_extract_pdf(self):
        extractor = AttachmentExtractor()
        
        # Mock PDF content
        content = b"%PDF-1.4 mock content"
        
        result = extractor.extract(
            filename="invoice.pdf",
            content=content,
            content_type="application/pdf",
        )
        
        assert len(result.files) == 1
        assert result.files[0].filename == "invoice.pdf"
        assert result.files[0].content_type == "application/pdf"

    def test_extract_image(self):
        extractor = AttachmentExtractor()
        
        # Mock PNG content
        content = b"\x89PNG\r\n\x1a\nmock image"
        
        result = extractor.extract(
            filename="receipt.png",
            content=content,
            content_type="image/png",
        )
        
        assert len(result.files) == 1
        assert result.files[0].filename == "receipt.png"

    def test_reject_executable(self):
        extractor = AttachmentExtractor()
        
        content = b"MZ executable content"
        
        result = extractor.extract(
            filename="virus.exe",
            content=content,
            content_type="application/x-msdownload",
        )
        
        assert len(result.files) == 0
        assert len(result.errors) > 0

    def test_reject_dangerous_extension(self):
        extractor = AttachmentExtractor()
        
        result = extractor.extract(
            filename="script.bat",
            content=b"echo hello",
            content_type="text/plain",
        )
        
        assert len(result.files) == 0
        assert len(result.errors) > 0

    def test_file_size_limit(self):
        extractor = AttachmentExtractor(max_file_size=100)
        
        large_content = b"x" * 200
        
        result = extractor.extract(
            filename="large.pdf",
            content=large_content,
            content_type="application/pdf",
        )
        
        assert len(result.files) == 0
        assert len(result.errors) > 0

    def test_validate_magic_bytes(self):
        extractor = AttachmentExtractor()
        
        # Valid PDF magic bytes
        valid_pdf = b"%PDF-1.4 content"
        assert extractor.validate_content_matches_type(valid_pdf, "application/pdf")
        
        # Invalid PDF (wrong magic bytes)
        invalid_pdf = b"not a pdf"
        assert not extractor.validate_content_matches_type(invalid_pdf, "application/pdf")


class TestContentExtractor:
    """Tests for content extraction from documents."""

    def test_extract_csv(self):
        extractor = ContentExtractor()
        
        csv_content = b"Name,Amount,Date\nVendor A,100.00,2024-01-15\nVendor B,200.00,2024-01-16"
        
        result = extractor.extract(csv_content, "text/csv", "data.csv")
        
        assert len(result.tables) == 1
        assert len(result.tables[0]) == 3  # Header + 2 rows
        assert "Vendor A" in result.text

    def test_extract_html(self):
        extractor = ContentExtractor()
        
        html = """
        <html>
        <body>
        <h1>Invoice</h1>
        <table>
            <tr><td>Item</td><td>Price</td></tr>
            <tr><td>Widget</td><td>$100</td></tr>
        </table>
        <a href="https://example.com/invoice.pdf">Download PDF</a>
        </body>
        </html>
        """
        
        result = extractor.extract_from_html(html)
        
        assert "Invoice" in result.text
        assert len(result.tables) > 0
        assert result.metadata.get("has_tables")

    def test_needs_ocr_detection(self):
        extractor = ContentExtractor()
        
        # Image content
        image_content = b"\x89PNG\r\n\x1a\nimage data"
        
        result = extractor.extract(image_content, "image/png", "scan.png")
        
        assert result.metadata.get("needs_ocr") is True
        assert result.text == ""





