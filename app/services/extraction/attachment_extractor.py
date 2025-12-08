import io
import logging
import mimetypes
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Supported file types
SUPPORTED_TYPES = {
    # Documents
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    # Images
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/tiff": "tiff",
    # Archives
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
}

# Dangerous file types to reject
DANGEROUS_TYPES = {
    "application/x-executable",
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-sh",
    "application/x-bat",
    "text/x-python",
    "text/x-script.python",
}

DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
    ".vbs", ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1",
}


@dataclass
class ExtractedFile:
    """Represents an extracted file from an attachment."""
    filename: str
    content: bytes
    content_type: str
    size: int
    original_filename: str  # Original attachment filename
    extracted_from_archive: bool = False
    archive_path: Optional[str] = None  # Path within archive


@dataclass
class ExtractionResult:
    """Result of attachment extraction."""
    files: list[ExtractedFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class AttachmentExtractor:
    """
    Extracts and validates attachments from emails.
    
    Handles:
    - Direct file attachments (PDF, XLSX, CSV, DOCX, images)
    - Archive extraction (ZIP files)
    - File type validation
    - Security checks
    """

    def __init__(self, max_file_size: int = 50 * 1024 * 1024):  # 50MB default
        self.max_file_size = max_file_size

    def extract(
        self,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> ExtractionResult:
        """
        Extract files from an attachment.
        
        Args:
            filename: Original filename of the attachment
            content: Binary content of the attachment
            content_type: MIME type of the attachment
        
        Returns:
            ExtractionResult containing extracted files, errors, and skipped files.
        """
        result = ExtractionResult()

        # Validate content type
        if not self._is_valid_content_type(content_type, filename):
            result.skipped.append(f"{filename}: Unsupported file type {content_type}")
            return result

        # Check for dangerous files
        if self._is_dangerous(filename, content_type):
            result.errors.append(f"{filename}: Dangerous file type rejected")
            return result

        # Check file size
        if len(content) > self.max_file_size:
            result.errors.append(f"{filename}: File too large ({len(content)} bytes)")
            return result

        # Handle archives
        if self._is_archive(content_type, filename):
            return self._extract_archive(filename, content)

        # Handle regular files
        extracted = ExtractedFile(
            filename=filename,
            content=content,
            content_type=content_type,
            size=len(content),
            original_filename=filename,
            extracted_from_archive=False,
        )
        result.files.append(extracted)
        return result

    def _extract_archive(self, filename: str, content: bytes) -> ExtractionResult:
        """Extract files from a ZIP archive."""
        result = ExtractionResult()

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for info in zf.infolist():
                    # Skip directories
                    if info.is_dir():
                        continue

                    inner_filename = Path(info.filename).name
                    
                    # Skip hidden files
                    if inner_filename.startswith("."):
                        continue

                    # Check for dangerous files
                    inner_type = mimetypes.guess_type(inner_filename)[0] or "application/octet-stream"
                    if self._is_dangerous(inner_filename, inner_type):
                        result.errors.append(f"{inner_filename}: Dangerous file in archive rejected")
                        continue

                    # Check if supported
                    if not self._is_valid_content_type(inner_type, inner_filename):
                        result.skipped.append(f"{inner_filename}: Unsupported file type in archive")
                        continue

                    # Extract file
                    try:
                        inner_content = zf.read(info.filename)
                        
                        # Check size
                        if len(inner_content) > self.max_file_size:
                            result.errors.append(f"{inner_filename}: File in archive too large")
                            continue

                        extracted = ExtractedFile(
                            filename=inner_filename,
                            content=inner_content,
                            content_type=inner_type,
                            size=len(inner_content),
                            original_filename=filename,
                            extracted_from_archive=True,
                            archive_path=info.filename,
                        )
                        result.files.append(extracted)
                    except Exception as e:
                        result.errors.append(f"{inner_filename}: Error extracting - {str(e)}")

        except zipfile.BadZipFile:
            result.errors.append(f"{filename}: Invalid or corrupted ZIP file")
        except Exception as e:
            result.errors.append(f"{filename}: Error processing archive - {str(e)}")

        return result

    def _is_valid_content_type(self, content_type: str, filename: str) -> bool:
        """Check if the content type is supported."""
        # Check MIME type
        if content_type in SUPPORTED_TYPES:
            return True

        # Check by extension
        ext = Path(filename).suffix.lower()
        valid_extensions = {f".{v}" for v in SUPPORTED_TYPES.values()}
        if ext in valid_extensions:
            return True

        # Additional check for common types
        if content_type in ("application/octet-stream", ""):
            # Try to determine by extension
            guessed_type = mimetypes.guess_type(filename)[0]
            if guessed_type in SUPPORTED_TYPES:
                return True

        return False

    def _is_dangerous(self, filename: str, content_type: str) -> bool:
        """Check if the file is potentially dangerous."""
        # Check content type
        if content_type in DANGEROUS_TYPES:
            return True

        # Check extension
        ext = Path(filename).suffix.lower()
        if ext in DANGEROUS_EXTENSIONS:
            return True

        return False

    def _is_archive(self, content_type: str, filename: str) -> bool:
        """Check if the file is an archive."""
        if content_type in ("application/zip", "application/x-zip-compressed"):
            return True
        if Path(filename).suffix.lower() == ".zip":
            return True
        return False

    def validate_content_matches_type(self, content: bytes, claimed_type: str) -> bool:
        """
        Validate that file content matches claimed MIME type.
        Uses magic bytes to verify.
        """
        # Magic bytes for common types
        magic_signatures = {
            "application/pdf": [b"%PDF"],
            "application/zip": [b"PK\x03\x04", b"PK\x05\x06"],
            "image/jpeg": [b"\xff\xd8\xff"],
            "image/png": [b"\x89PNG\r\n\x1a\n"],
            "image/gif": [b"GIF87a", b"GIF89a"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [b"PK\x03\x04"],  # XLSX is ZIP
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [b"PK\x03\x04"],  # DOCX is ZIP
        }

        signatures = magic_signatures.get(claimed_type, [])
        if not signatures:
            return True  # Can't validate, assume OK

        for sig in signatures:
            if content.startswith(sig):
                return True

        logger.warning(f"Content does not match claimed type: {claimed_type}")
        return False




