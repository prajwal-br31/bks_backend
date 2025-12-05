"""Service for extracting and processing email attachments."""

import hashlib
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Tuple
import structlog

from .email_adapter import EmailAttachment

logger = structlog.get_logger()

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    '.pdf', '.xlsx', '.xls', '.csv', 
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
    '.docx', '.doc',
    '.zip'
}

# MIME types mapping
MIME_TYPE_EXTENSIONS = {
    'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.ms-excel': '.xls',
    'text/csv': '.csv',
    'application/csv': '.csv',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/bmp': '.bmp',
    'image/tiff': '.tiff',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/msword': '.doc',
    'application/zip': '.zip',
    'application/x-zip-compressed': '.zip',
}

# Dangerous extensions that should be rejected
DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.com', '.msi', '.scr',
    '.vbs', '.vbe', '.js', '.jse', '.ws', '.wsf',
    '.ps1', '.psm1', '.psd1',
    '.dll', '.sys', '.drv',
    '.sh', '.bash', '.csh', '.ksh',
}


@dataclass
class ExtractedFile:
    """Represents an extracted file ready for processing."""
    filename: str
    content: bytes
    content_type: str
    size: int
    file_hash: str  # SHA-256
    source_attachment: str  # Original attachment filename
    is_from_archive: bool = False


class AttachmentExtractor:
    """Service for extracting files from email attachments."""
    
    def __init__(self, max_file_size: int = 50 * 1024 * 1024):  # 50MB default
        self.max_file_size = max_file_size
    
    def extract_all(self, attachments: List[EmailAttachment]) -> List[ExtractedFile]:
        """Extract all processable files from attachments."""
        extracted_files = []
        
        for attachment in attachments:
            try:
                files = self._process_attachment(attachment)
                extracted_files.extend(files)
            except Exception as e:
                logger.error(
                    "Error extracting attachment",
                    filename=attachment.filename,
                    error=str(e)
                )
        
        return extracted_files
    
    def _process_attachment(self, attachment: EmailAttachment) -> List[ExtractedFile]:
        """Process a single attachment, extracting files if archive."""
        files = []
        
        # Validate file
        if not self._is_safe_file(attachment.filename, attachment.content):
            logger.warning(
                "Unsafe file rejected",
                filename=attachment.filename
            )
            return files
        
        # Check size
        if attachment.size > self.max_file_size:
            logger.warning(
                "File too large",
                filename=attachment.filename,
                size=attachment.size,
                max_size=self.max_file_size
            )
            return files
        
        # Check if it's a supported type
        ext = self._get_extension(attachment.filename, attachment.content_type)
        
        if ext == '.zip':
            # Extract archive contents
            files.extend(self._extract_archive(attachment))
        elif ext in SUPPORTED_EXTENSIONS:
            # Single file
            files.append(ExtractedFile(
                filename=attachment.filename,
                content=attachment.content,
                content_type=attachment.content_type,
                size=attachment.size,
                file_hash=self._compute_hash(attachment.content),
                source_attachment=attachment.filename,
                is_from_archive=False
            ))
        else:
            logger.info(
                "Unsupported file type",
                filename=attachment.filename,
                extension=ext
            )
        
        return files
    
    def _extract_archive(self, attachment: EmailAttachment) -> List[ExtractedFile]:
        """Extract files from a ZIP archive."""
        files = []
        
        try:
            with zipfile.ZipFile(io.BytesIO(attachment.content), 'r') as zf:
                for name in zf.namelist():
                    # Skip directories
                    if name.endswith('/'):
                        continue
                    
                    # Get file info
                    info = zf.getinfo(name)
                    
                    # Skip large files
                    if info.file_size > self.max_file_size:
                        logger.warning(
                            "Archived file too large",
                            filename=name,
                            size=info.file_size
                        )
                        continue
                    
                    # Check if safe
                    if not self._is_safe_filename(name):
                        logger.warning(
                            "Unsafe archived file rejected",
                            filename=name
                        )
                        continue
                    
                    # Get extension
                    ext = os.path.splitext(name)[1].lower()
                    
                    # Only extract supported types (excluding nested zips)
                    if ext not in SUPPORTED_EXTENSIONS or ext == '.zip':
                        continue
                    
                    # Extract content
                    content = zf.read(name)
                    content_type = self._guess_content_type(name)
                    
                    files.append(ExtractedFile(
                        filename=os.path.basename(name),
                        content=content,
                        content_type=content_type,
                        size=len(content),
                        file_hash=self._compute_hash(content),
                        source_attachment=attachment.filename,
                        is_from_archive=True
                    ))
                    
        except zipfile.BadZipFile:
            logger.error("Invalid ZIP file", filename=attachment.filename)
        except Exception as e:
            logger.error("Error extracting ZIP", filename=attachment.filename, error=str(e))
        
        return files
    
    def _is_safe_file(self, filename: str, content: bytes) -> bool:
        """Check if file is safe to process."""
        # Check filename
        if not self._is_safe_filename(filename):
            return False
        
        # Check for executable content
        if self._is_executable_content(content):
            return False
        
        return True
    
    def _is_safe_filename(self, filename: str) -> bool:
        """Check if filename is safe."""
        ext = os.path.splitext(filename)[1].lower()
        
        # Check for dangerous extensions
        if ext in DANGEROUS_EXTENSIONS:
            return False
        
        # Check for double extensions (e.g., .pdf.exe)
        parts = filename.lower().split('.')
        for part in parts[1:]:  # Skip the first part (actual filename)
            if f'.{part}' in DANGEROUS_EXTENSIONS:
                return False
        
        return True
    
    def _is_executable_content(self, content: bytes) -> bool:
        """Check if content appears to be executable."""
        # Check for common executable signatures
        signatures = [
            b'MZ',  # Windows PE
            b'\x7fELF',  # Linux ELF
            b'#!/',  # Shell script
            b'PK\x03\x04',  # Could be docx/xlsx or zip (let through for now)
        ]
        
        # Only reject clear executables
        if content[:2] == b'MZ' or content[:4] == b'\x7fELF':
            return True
        
        return False
    
    def _get_extension(self, filename: str, content_type: str) -> str:
        """Get file extension, using MIME type as fallback."""
        ext = os.path.splitext(filename)[1].lower()
        
        if ext and ext in SUPPORTED_EXTENSIONS:
            return ext
        
        # Try to determine from content type
        return MIME_TYPE_EXTENSIONS.get(content_type, ext)
    
    def _guess_content_type(self, filename: str) -> str:
        """Guess content type from filename."""
        ext = os.path.splitext(filename)[1].lower()
        
        content_types = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.csv': 'text/csv',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
        }
        
        return content_types.get(ext, 'application/octet-stream')
    
    def _compute_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()

