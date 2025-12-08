from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    content_type: str
    content: bytes
    size: int
    content_id: Optional[str] = None  # For inline images


@dataclass
class EmailMessage:
    """Represents a parsed email message."""
    uid: str  # Unique identifier from mail server
    message_id: str  # Message-ID header
    from_address: str
    to_addresses: list[str]
    subject: str
    date: datetime
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    attachments: list[EmailAttachment] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    is_read: bool = False
    raw_headers: dict = field(default_factory=dict)

    def get_sender_domain(self) -> str:
        """Extract domain from sender email."""
        if "@" in self.from_address:
            return self.from_address.split("@")[-1].lower().strip(">")
        return ""


class EmailAdapter(ABC):
    """Abstract base class for email adapters."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the email server."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the email server."""
        pass

    @abstractmethod
    async def fetch_unread_emails(
        self,
        folder: str = "INBOX",
        limit: int = 50,
        since: Optional[datetime] = None,
    ) -> list[EmailMessage]:
        """Fetch unread emails from the specified folder."""
        pass

    @abstractmethod
    async def fetch_email_by_uid(self, uid: str, folder: str = "INBOX") -> Optional[EmailMessage]:
        """Fetch a specific email by its UID."""
        pass

    @abstractmethod
    async def mark_as_read(self, uid: str, folder: str = "INBOX") -> bool:
        """Mark an email as read."""
        pass

    @abstractmethod
    async def mark_as_processed(self, uid: str, folder: str = "INBOX") -> bool:
        """Mark an email as processed (apply label/move to folder)."""
        pass

    @abstractmethod
    async def get_folders(self) -> list[str]:
        """Get list of available folders/labels."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the connection is healthy."""
        pass

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()





