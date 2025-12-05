"""Virus scanning service using ClamAV."""

import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple
import structlog

import clamd

from ..core.config import get_settings

logger = structlog.get_logger()


@dataclass
class ScanResult:
    """Result of virus scan."""
    is_clean: bool
    virus_name: Optional[str] = None
    scanner: str = "none"
    error: Optional[str] = None


class VirusScanner(ABC):
    """Abstract base class for virus scanners."""
    
    @abstractmethod
    def scan(self, content: bytes, filename: str) -> ScanResult:
        """Scan file content for viruses."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if scanner is available."""
        pass


class NoOpScanner(VirusScanner):
    """No-op scanner that passes all files (for development)."""
    
    def scan(self, content: bytes, filename: str) -> ScanResult:
        """Always return clean."""
        logger.debug("NoOp virus scan (always clean)", filename=filename)
        return ScanResult(is_clean=True, scanner="none")
    
    def is_available(self) -> bool:
        """Always available."""
        return True


class ClamAVScanner(VirusScanner):
    """ClamAV-based virus scanner."""
    
    def __init__(self):
        self.settings = get_settings()
        self._client = None
    
    @property
    def client(self):
        """Lazy-initialize ClamAV client."""
        if self._client is None:
            try:
                self._client = clamd.ClamdNetworkSocket(
                    host=self.settings.clamav_host,
                    port=self.settings.clamav_port
                )
            except Exception as e:
                logger.error("Failed to connect to ClamAV", error=str(e))
                raise
        return self._client
    
    def scan(self, content: bytes, filename: str) -> ScanResult:
        """Scan file content using ClamAV."""
        try:
            # Use instream to scan the content
            result = self.client.instream(io.BytesIO(content))
            
            # Result is like {'stream': ('OK', None)} or {'stream': ('FOUND', 'Eicar-Test-Signature')}
            stream_result = result.get('stream', ('ERROR', 'Unknown'))
            status, virus_name = stream_result
            
            if status == 'OK':
                logger.info("File scan clean", filename=filename)
                return ScanResult(is_clean=True, scanner="clamav")
            elif status == 'FOUND':
                logger.warning(
                    "Virus detected",
                    filename=filename,
                    virus=virus_name
                )
                return ScanResult(
                    is_clean=False,
                    virus_name=virus_name,
                    scanner="clamav"
                )
            else:
                logger.error(
                    "Scan error",
                    filename=filename,
                    status=status
                )
                return ScanResult(
                    is_clean=False,
                    scanner="clamav",
                    error=f"Scan error: {status}"
                )
                
        except Exception as e:
            logger.error(
                "ClamAV scan failed",
                filename=filename,
                error=str(e)
            )
            return ScanResult(
                is_clean=False,
                scanner="clamav",
                error=str(e)
            )
    
    def is_available(self) -> bool:
        """Check if ClamAV is available."""
        try:
            self.client.ping()
            return True
        except Exception:
            return False


def get_virus_scanner() -> VirusScanner:
    """Factory function to get the appropriate virus scanner."""
    settings = get_settings()
    
    if settings.virus_scanner.lower() == "none":
        return NoOpScanner()
    
    # Try ClamAV
    scanner = ClamAVScanner()
    if scanner.is_available():
        return scanner
    
    # Fall back to NoOp if ClamAV not available
    logger.warning("ClamAV not available, falling back to NoOp scanner")
    return NoOpScanner()

