"""Tests for security services."""

import pytest
from app.services.security import FileValidator, ValidationResult


class TestFileValidator:
    """Tests for file validation."""

    def test_valid_pdf(self):
        validator = FileValidator()
        
        # Valid PDF with magic bytes
        content = b"%PDF-1.4 valid pdf content"
        
        result = validator.validate(content, "invoice.pdf", "application/pdf")
        
        assert result.is_valid
        assert result.detected_type == "application/pdf"

    def test_valid_png(self):
        validator = FileValidator()
        
        # Valid PNG with magic bytes
        content = b"\x89PNG\r\n\x1a\nvalid png content"
        
        result = validator.validate(content, "receipt.png", "image/png")
        
        assert result.is_valid
        assert result.detected_type == "image/png"

    def test_reject_executable(self):
        validator = FileValidator()
        
        # PE executable
        content = b"MZ\x90\x00executable content"
        
        result = validator.validate(content, "malware.exe", "application/octet-stream")
        
        assert not result.is_valid
        assert any("executable" in err.lower() for err in result.errors)

    def test_reject_dangerous_extension(self):
        validator = FileValidator()
        
        content = b"some content"
        
        # Test various dangerous extensions
        dangerous = [".exe", ".bat", ".cmd", ".ps1", ".vbs"]
        
        for ext in dangerous:
            result = validator.validate(content, f"file{ext}", "application/octet-stream")
            assert not result.is_valid

    def test_reject_empty_file(self):
        validator = FileValidator()
        
        result = validator.validate(b"", "empty.pdf", "application/pdf")
        
        assert not result.is_valid
        assert any("empty" in err.lower() for err in result.errors)

    def test_reject_oversized_file(self):
        validator = FileValidator(max_file_size=100)
        
        large_content = b"x" * 200
        
        result = validator.validate(large_content, "large.pdf", "application/pdf")
        
        assert not result.is_valid
        assert any("large" in err.lower() for err in result.errors)

    def test_warn_type_mismatch(self):
        validator = FileValidator()
        
        # PNG content claimed as PDF
        png_content = b"\x89PNG\r\n\x1a\npng content"
        
        result = validator.validate(png_content, "file.pdf", "application/pdf")
        
        # Should warn but still be valid (it's a valid image)
        assert len(result.warnings) > 0

    def test_sanitize_filename(self):
        validator = FileValidator()
        
        # Path traversal attempt
        assert validator.sanitize_filename("../../../etc/passwd") == "passwd"
        
        # Control characters
        assert validator.sanitize_filename("file\x00name.pdf") == "filename.pdf"
        
        # Dangerous characters
        assert validator.sanitize_filename('file<>:"/\\|?*.pdf') == "file_________.pdf"
        
        # Long filename
        long_name = "a" * 300 + ".pdf"
        sanitized = validator.sanitize_filename(long_name)
        assert len(sanitized) <= 204  # 150 + ext

    def test_detect_path_traversal(self):
        validator = FileValidator()
        
        issues = validator._validate_filename("../secret.pdf")
        assert len(issues) > 0

    def test_detect_double_extension(self):
        validator = FileValidator()
        
        issues = validator._validate_filename("invoice.pdf.exe")
        assert len(issues) > 0





