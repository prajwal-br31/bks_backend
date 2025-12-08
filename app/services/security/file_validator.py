import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of file validation."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_type: Optional[str] = None


class FileValidator:
    """
    Validates files for security and compliance.
    
    Checks:
    - File type vs content (magic bytes)
    - Dangerous file types
    - File size limits
    - Filename sanitization
    """

    # Magic bytes for file type detection
    MAGIC_SIGNATURES = {
        "application/pdf": [(0, b"%PDF")],
        "image/jpeg": [(0, b"\xff\xd8\xff")],
        "image/png": [(0, b"\x89PNG\r\n\x1a\n")],
        "image/gif": [(0, b"GIF87a"), (0, b"GIF89a")],
        "application/zip": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06")],
        "application/gzip": [(0, b"\x1f\x8b")],
        "image/webp": [(0, b"RIFF"), (8, b"WEBP")],
        "image/tiff": [(0, b"II\x2a\x00"), (0, b"MM\x00\x2a")],
    }

    # Dangerous extensions
    DANGEROUS_EXTENSIONS = {
        ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
        ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
        ".ps1", ".psm1", ".psd1",
        ".dll", ".sys", ".drv",
        ".app", ".dmg", ".pkg",
        ".sh", ".bash", ".zsh",
        ".jar", ".class",
    }

    # Allowed extensions
    ALLOWED_EXTENSIONS = {
        ".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc",
        ".jpg", ".jpeg", ".png", ".gif", ".tiff", ".tif", ".webp",
        ".zip",
    }

    def __init__(self, max_file_size: int = 50 * 1024 * 1024):
        self.max_file_size = max_file_size

    def validate(
        self,
        content: bytes,
        filename: str,
        claimed_type: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate a file.
        
        Args:
            content: File content as bytes
            filename: Filename
            claimed_type: Claimed MIME type
        
        Returns:
            ValidationResult
        """
        result = ValidationResult(is_valid=True)
        ext = Path(filename).suffix.lower()

        # Check file size
        if len(content) > self.max_file_size:
            result.is_valid = False
            result.errors.append(f"File too large: {len(content)} bytes (max: {self.max_file_size})")
            return result

        # Check for empty file
        if len(content) == 0:
            result.is_valid = False
            result.errors.append("File is empty")
            return result

        # Check dangerous extensions
        if ext in self.DANGEROUS_EXTENSIONS:
            result.is_valid = False
            result.errors.append(f"Dangerous file type: {ext}")
            return result

        # Check allowed extensions
        if ext not in self.ALLOWED_EXTENSIONS:
            result.warnings.append(f"Unusual file extension: {ext}")

        # Detect actual file type
        detected_type = self._detect_type(content)
        result.detected_type = detected_type

        # Verify claimed type matches content
        if claimed_type and detected_type:
            if not self._types_compatible(claimed_type, detected_type):
                result.warnings.append(
                    f"Claimed type ({claimed_type}) doesn't match detected ({detected_type})"
                )

        # Check for executable content in non-executable files
        if self._contains_executable_markers(content) and ext not in {".zip"}:
            result.is_valid = False
            result.errors.append("File contains executable content")
            return result

        # Validate filename
        filename_issues = self._validate_filename(filename)
        result.warnings.extend(filename_issues)

        return result

    def _detect_type(self, content: bytes) -> Optional[str]:
        """Detect file type from magic bytes."""
        for mime_type, signatures in self.MAGIC_SIGNATURES.items():
            for offset, signature in signatures:
                if len(content) > offset + len(signature):
                    if content[offset:offset + len(signature)] == signature:
                        return mime_type
        return None

    def _types_compatible(self, claimed: str, detected: str) -> bool:
        """Check if claimed and detected types are compatible."""
        # Direct match
        if claimed == detected:
            return True

        # XLSX/DOCX are ZIP files internally
        if detected == "application/zip" and claimed in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            return True

        # Image type variations
        if claimed.startswith("image/") and detected.startswith("image/"):
            return True

        return False

    def _contains_executable_markers(self, content: bytes) -> bool:
        """Check for executable content markers."""
        # PE executable (Windows)
        if content[:2] == b"MZ":
            return True

        # ELF executable (Linux)
        if content[:4] == b"\x7fELF":
            return True

        # Mach-O (macOS)
        if content[:4] in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"}:
            return True

        # Script markers in first 1KB
        script_markers = [b"#!/", b"#!python", b"#!bash", b"@echo off", b"powershell"]
        first_kb = content[:1024]
        for marker in script_markers:
            if marker in first_kb:
                return True

        return False

    def _validate_filename(self, filename: str) -> list[str]:
        """Validate filename for security issues."""
        issues = []

        # Check for path traversal attempts
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            issues.append("Filename contains path traversal characters")

        # Check for null bytes
        if "\x00" in filename:
            issues.append("Filename contains null bytes")

        # Check for control characters
        if any(ord(c) < 32 for c in filename):
            issues.append("Filename contains control characters")

        # Check length
        if len(filename) > 255:
            issues.append("Filename too long")

        # Check for double extensions (e.g., file.pdf.exe)
        parts = filename.split(".")
        if len(parts) > 2:
            for part in parts[1:-1]:
                if f".{part}" in self.DANGEROUS_EXTENSIONS:
                    issues.append(f"Suspicious double extension: {filename}")

        return issues

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe storage."""
        # Remove path components
        filename = Path(filename).name

        # Remove control characters
        filename = "".join(c for c in filename if ord(c) >= 32)

        # Remove/replace dangerous characters
        dangerous_chars = '<>:"/\\|?*'
        for char in dangerous_chars:
            filename = filename.replace(char, "_")

        # Limit length
        if len(filename) > 200:
            name = Path(filename).stem[:150]
            ext = Path(filename).suffix
            filename = f"{name}{ext}"

        return filename or "unnamed_file"




