import asyncio
import logging
import socket
from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of virus scan."""
    is_clean: bool
    virus_name: Optional[str] = None
    error: Optional[str] = None
    scan_time_ms: float = 0.0


class VirusScanner:
    """
    Virus scanner using ClamAV daemon.
    
    Connects to clamd via TCP socket to scan files.
    """

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        settings = get_settings()
        self.host = host or settings.clamav_host
        self.port = port or settings.clamav_port
        self.enabled = settings.virus_scanner == "clamav"
        self._timeout = 30  # seconds

    async def scan(self, content: bytes) -> ScanResult:
        """
        Scan file content for viruses.
        
        Args:
            content: File content as bytes
        
        Returns:
            ScanResult indicating if file is clean
        """
        if not self.enabled:
            return ScanResult(is_clean=True, error="Scanner disabled")

        import time
        start_time = time.time()

        def _scan():
            try:
                # Connect to ClamAV daemon
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self._timeout)
                sock.connect((self.host, self.port))

                try:
                    # Use INSTREAM command for scanning content
                    sock.sendall(b"nINSTREAM\n")

                    # Send content in chunks
                    chunk_size = 2048
                    for i in range(0, len(content), chunk_size):
                        chunk = content[i:i + chunk_size]
                        size = len(chunk)
                        sock.sendall(size.to_bytes(4, byteorder='big') + chunk)

                    # Send zero-length chunk to indicate end
                    sock.sendall((0).to_bytes(4, byteorder='big'))

                    # Receive response
                    response = b""
                    while True:
                        data = sock.recv(4096)
                        if not data:
                            break
                        response += data
                        if b"\n" in data:
                            break

                    response_str = response.decode('utf-8').strip()
                    elapsed = (time.time() - start_time) * 1000

                    # Parse response
                    # Format: "stream: OK" or "stream: VirusName FOUND"
                    if "OK" in response_str:
                        return ScanResult(is_clean=True, scan_time_ms=elapsed)
                    elif "FOUND" in response_str:
                        # Extract virus name
                        parts = response_str.split(":")
                        if len(parts) >= 2:
                            virus_info = parts[1].strip()
                            virus_name = virus_info.replace("FOUND", "").strip()
                        else:
                            virus_name = "Unknown"
                        return ScanResult(
                            is_clean=False,
                            virus_name=virus_name,
                            scan_time_ms=elapsed,
                        )
                    else:
                        return ScanResult(
                            is_clean=True,
                            error=f"Unexpected response: {response_str}",
                            scan_time_ms=elapsed,
                        )

                finally:
                    sock.close()

            except socket.timeout:
                return ScanResult(is_clean=True, error="Scan timeout")
            except ConnectionRefusedError:
                logger.warning("ClamAV not available, skipping scan")
                return ScanResult(is_clean=True, error="ClamAV not available")
            except Exception as e:
                logger.error(f"Virus scan error: {e}")
                return ScanResult(is_clean=True, error=str(e))

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _scan)

    async def health_check(self) -> bool:
        """Check if ClamAV is available."""
        if not self.enabled:
            return True

        def _check():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.host, self.port))
                
                try:
                    # Send PING command
                    sock.sendall(b"nPING\n")
                    response = sock.recv(1024).decode('utf-8').strip()
                    return response == "PONG"
                finally:
                    sock.close()
            except Exception as e:
                logger.error(f"ClamAV health check failed: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    async def get_version(self) -> Optional[str]:
        """Get ClamAV version."""
        if not self.enabled:
            return None

        def _get_version():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.host, self.port))
                
                try:
                    sock.sendall(b"nVERSION\n")
                    response = sock.recv(1024).decode('utf-8').strip()
                    return response
                finally:
                    sock.close()
            except Exception:
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_version)





