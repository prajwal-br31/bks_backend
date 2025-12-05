"""Email adapters for IMAP and Gmail API."""

import email
import imaplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header
from email.message import Message
from typing import List, Optional, Tuple, Generator
import structlog

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64

from ..core.config import get_settings

logger = structlog.get_logger()


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    content_type: str
    content: bytes
    size: int
    content_id: Optional[str] = None  # For inline images


@dataclass
class ParsedEmail:
    """Represents a parsed email message."""
    message_id: str
    thread_id: Optional[str]
    from_address: str
    to_addresses: List[str]
    cc_addresses: List[str]
    subject: str
    received_date: datetime
    body_text: Optional[str]
    body_html: Optional[str]
    attachments: List[EmailAttachment] = field(default_factory=list)
    raw_message: Optional[bytes] = None


class EmailAdapter(ABC):
    """Abstract base class for email adapters."""
    
    @abstractmethod
    def connect(self) -> None:
        """Establish connection to email server."""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to email server."""
        pass
    
    @abstractmethod
    def fetch_new_emails(self, since: Optional[datetime] = None) -> Generator[ParsedEmail, None, None]:
        """Fetch new emails since the given date."""
        pass
    
    @abstractmethod
    def mark_as_processed(self, message_id: str) -> None:
        """Mark an email as processed (e.g., move to folder, add label)."""
        pass
    
    def is_whitelisted(self, email_address: str) -> bool:
        """Check if email address is whitelisted."""
        settings = get_settings()
        
        # If no whitelist configured, allow all
        if not settings.whitelist_domains_list and not settings.whitelist_addresses_list:
            return True
        
        email_lower = email_address.lower()
        
        # Check exact address match
        if email_lower in [a.lower() for a in settings.whitelist_addresses_list]:
            return True
        
        # Check domain match
        domain = email_lower.split("@")[-1] if "@" in email_lower else ""
        if domain in [d.lower() for d in settings.whitelist_domains_list]:
            return True
        
        return False


class IMAPAdapter(EmailAdapter):
    """IMAP email adapter."""
    
    def __init__(self):
        self.settings = get_settings()
        self.connection: Optional[imaplib.IMAP4_SSL] = None
    
    def connect(self) -> None:
        """Connect to IMAP server."""
        try:
            if self.settings.imap_use_ssl:
                self.connection = imaplib.IMAP4_SSL(
                    self.settings.imap_host, 
                    self.settings.imap_port
                )
            else:
                self.connection = imaplib.IMAP4(
                    self.settings.imap_host,
                    self.settings.imap_port
                )
            
            self.connection.login(
                self.settings.imap_username,
                self.settings.imap_password
            )
            
            logger.info(
                "IMAP connection established",
                host=self.settings.imap_host,
                user=self.settings.imap_username
            )
        except Exception as e:
            logger.error("IMAP connection failed", error=str(e))
            raise
    
    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self.connection:
            try:
                self.connection.close()
                self.connection.logout()
            except Exception:
                pass
            self.connection = None
    
    def fetch_new_emails(self, since: Optional[datetime] = None) -> Generator[ParsedEmail, None, None]:
        """Fetch new emails from IMAP server."""
        if not self.connection:
            self.connect()
        
        try:
            # Select folder
            self.connection.select(self.settings.imap_folder)
            
            # Build search criteria
            search_criteria = "UNSEEN"
            if since:
                date_str = since.strftime("%d-%b-%Y")
                search_criteria = f'(UNSEEN SINCE {date_str})'
            
            # Search for emails
            _, message_numbers = self.connection.search(None, search_criteria)
            
            for num in message_numbers[0].split():
                try:
                    _, msg_data = self.connection.fetch(num, "(RFC822)")
                    
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            raw_email = response_part[1]
                            email_message = email.message_from_bytes(raw_email)
                            parsed = self._parse_email(email_message, raw_email)
                            
                            # Check whitelist
                            if self.is_whitelisted(parsed.from_address):
                                yield parsed
                            else:
                                logger.info(
                                    "Skipping non-whitelisted email",
                                    from_address=parsed.from_address
                                )
                except Exception as e:
                    logger.error("Error processing email", error=str(e), num=num)
                    continue
                    
        except Exception as e:
            logger.error("Error fetching emails", error=str(e))
            raise
    
    def mark_as_processed(self, message_id: str) -> None:
        """Mark email as seen and optionally move to processed folder."""
        if not self.connection:
            return
        
        try:
            # Search for the message by Message-ID
            self.connection.select(self.settings.imap_folder)
            _, message_numbers = self.connection.search(
                None, 
                f'HEADER Message-ID "{message_id}"'
            )
            
            for num in message_numbers[0].split():
                # Mark as seen
                self.connection.store(num, '+FLAGS', '\\Seen')
                
        except Exception as e:
            logger.error("Error marking email as processed", error=str(e))
    
    def _parse_email(self, msg: Message, raw: bytes) -> ParsedEmail:
        """Parse email message into ParsedEmail object."""
        # Decode subject
        subject = ""
        if msg["subject"]:
            decoded = decode_header(msg["subject"])
            subject_parts = []
            for part, encoding in decoded:
                if isinstance(part, bytes):
                    subject_parts.append(part.decode(encoding or "utf-8", errors="replace"))
                else:
                    subject_parts.append(part)
            subject = " ".join(subject_parts)
        
        # Parse addresses
        from_addr = self._extract_email_address(msg.get("from", ""))
        to_addrs = self._extract_email_addresses(msg.get("to", ""))
        cc_addrs = self._extract_email_addresses(msg.get("cc", ""))
        
        # Parse date
        date_str = msg.get("date", "")
        try:
            received_date = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            received_date = datetime.utcnow()
        
        # Extract body and attachments
        body_text = None
        body_html = None
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in content_disposition or part.get_filename():
                    # This is an attachment
                    attachment = self._extract_attachment(part)
                    if attachment:
                        attachments.append(attachment)
                elif content_type == "text/plain" and not body_text:
                    body_text = self._decode_payload(part)
                elif content_type == "text/html" and not body_html:
                    body_html = self._decode_payload(part)
                elif content_type.startswith("image/"):
                    # Inline image
                    attachment = self._extract_attachment(part)
                    if attachment:
                        attachments.append(attachment)
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                body_text = self._decode_payload(msg)
            elif content_type == "text/html":
                body_html = self._decode_payload(msg)
        
        return ParsedEmail(
            message_id=msg.get("message-id", f"unknown-{datetime.utcnow().timestamp()}"),
            thread_id=msg.get("in-reply-to"),
            from_address=from_addr,
            to_addresses=to_addrs,
            cc_addresses=cc_addrs,
            subject=subject,
            received_date=received_date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            raw_message=raw
        )
    
    def _decode_payload(self, part: Message) -> Optional[str]:
        """Decode email part payload to string."""
        try:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        except Exception:
            pass
        return None
    
    def _extract_attachment(self, part: Message) -> Optional[EmailAttachment]:
        """Extract attachment from email part."""
        try:
            filename = part.get_filename()
            if filename:
                decoded = decode_header(filename)
                if decoded[0][1]:
                    filename = decoded[0][0].decode(decoded[0][1])
                elif isinstance(decoded[0][0], bytes):
                    filename = decoded[0][0].decode("utf-8", errors="replace")
                else:
                    filename = decoded[0][0]
            else:
                # Generate filename for inline content
                content_type = part.get_content_type()
                ext = content_type.split("/")[-1]
                filename = f"inline_{datetime.utcnow().timestamp()}.{ext}"
            
            content = part.get_payload(decode=True)
            if content:
                return EmailAttachment(
                    filename=filename,
                    content_type=part.get_content_type(),
                    content=content,
                    size=len(content),
                    content_id=part.get("Content-ID")
                )
        except Exception as e:
            logger.error("Error extracting attachment", error=str(e))
        return None
    
    def _extract_email_address(self, header: str) -> str:
        """Extract email address from header."""
        if not header:
            return ""
        
        # Try to extract just the email part
        import re
        match = re.search(r'<([^>]+)>', header)
        if match:
            return match.group(1).lower()
        
        # Might be just the email
        if "@" in header:
            return header.strip().lower()
        
        return header.lower()
    
    def _extract_email_addresses(self, header: str) -> List[str]:
        """Extract multiple email addresses from header."""
        if not header:
            return []
        
        addresses = []
        for addr in header.split(","):
            extracted = self._extract_email_address(addr.strip())
            if extracted:
                addresses.append(extracted)
        return addresses


class GmailAdapter(EmailAdapter):
    """Gmail API email adapter."""
    
    def __init__(self):
        self.settings = get_settings()
        self.service = None
    
    def connect(self) -> None:
        """Connect to Gmail API."""
        try:
            credentials = Credentials(
                token=None,
                refresh_token=self.settings.gmail_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.settings.gmail_client_id,
                client_secret=self.settings.gmail_client_secret
            )
            
            self.service = build("gmail", "v1", credentials=credentials)
            
            logger.info("Gmail API connection established")
        except Exception as e:
            logger.error("Gmail API connection failed", error=str(e))
            raise
    
    def disconnect(self) -> None:
        """Disconnect from Gmail API."""
        self.service = None
    
    def fetch_new_emails(self, since: Optional[datetime] = None) -> Generator[ParsedEmail, None, None]:
        """Fetch new emails from Gmail."""
        if not self.service:
            self.connect()
        
        try:
            # Build query
            query_parts = ["is:unread"]
            
            if self.settings.gmail_label:
                query_parts.append(f"label:{self.settings.gmail_label}")
            
            if since:
                date_str = since.strftime("%Y/%m/%d")
                query_parts.append(f"after:{date_str}")
            
            query = " ".join(query_parts)
            
            # List messages
            results = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=50
            ).execute()
            
            messages = results.get("messages", [])
            
            for msg_ref in messages:
                try:
                    # Get full message
                    msg = self.service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full"
                    ).execute()
                    
                    parsed = self._parse_gmail_message(msg)
                    
                    # Check whitelist
                    if self.is_whitelisted(parsed.from_address):
                        yield parsed
                    else:
                        logger.info(
                            "Skipping non-whitelisted email",
                            from_address=parsed.from_address
                        )
                except Exception as e:
                    logger.error("Error processing Gmail message", error=str(e))
                    continue
                    
        except HttpError as e:
            logger.error("Gmail API error", error=str(e))
            raise
    
    def mark_as_processed(self, message_id: str) -> None:
        """Remove UNREAD label from Gmail message."""
        if not self.service:
            return
        
        try:
            # Find message by Message-ID header
            results = self.service.users().messages().list(
                userId="me",
                q=f"rfc822msgid:{message_id}"
            ).execute()
            
            messages = results.get("messages", [])
            for msg in messages:
                self.service.users().messages().modify(
                    userId="me",
                    id=msg["id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                
        except HttpError as e:
            logger.error("Error marking Gmail message as processed", error=str(e))
    
    def _parse_gmail_message(self, msg: dict) -> ParsedEmail:
        """Parse Gmail API message into ParsedEmail object."""
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        
        # Parse date
        internal_date = int(msg.get("internalDate", 0)) / 1000
        received_date = datetime.fromtimestamp(internal_date) if internal_date else datetime.utcnow()
        
        # Extract body and attachments
        body_text = None
        body_html = None
        attachments = []
        
        self._process_gmail_parts(
            msg["payload"],
            msg["id"],
            attachments,
            body_text_holder=[body_text],
            body_html_holder=[body_html]
        )
        
        return ParsedEmail(
            message_id=headers.get("message-id", msg["id"]),
            thread_id=msg.get("threadId"),
            from_address=self._extract_email_address(headers.get("from", "")),
            to_addresses=self._extract_email_addresses(headers.get("to", "")),
            cc_addresses=self._extract_email_addresses(headers.get("cc", "")),
            subject=headers.get("subject", ""),
            received_date=received_date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments
        )
    
    def _process_gmail_parts(
        self, 
        payload: dict, 
        message_id: str,
        attachments: List[EmailAttachment],
        body_text_holder: list,
        body_html_holder: list
    ) -> None:
        """Recursively process Gmail message parts."""
        mime_type = payload.get("mimeType", "")
        
        if "parts" in payload:
            for part in payload["parts"]:
                self._process_gmail_parts(
                    part, message_id, attachments, body_text_holder, body_html_holder
                )
        else:
            body = payload.get("body", {})
            
            if body.get("attachmentId"):
                # This is an attachment
                attachment = self._fetch_gmail_attachment(
                    message_id,
                    body["attachmentId"],
                    payload.get("filename", "attachment"),
                    mime_type
                )
                if attachment:
                    attachments.append(attachment)
            elif body.get("data"):
                # This is body content
                content = base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="replace")
                
                if mime_type == "text/plain" and not body_text_holder[0]:
                    body_text_holder[0] = content
                elif mime_type == "text/html" and not body_html_holder[0]:
                    body_html_holder[0] = content
    
    def _fetch_gmail_attachment(
        self, 
        message_id: str, 
        attachment_id: str,
        filename: str,
        content_type: str
    ) -> Optional[EmailAttachment]:
        """Fetch attachment content from Gmail API."""
        try:
            attachment = self.service.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id
            ).execute()
            
            content = base64.urlsafe_b64decode(attachment["data"])
            
            return EmailAttachment(
                filename=filename,
                content_type=content_type,
                content=content,
                size=len(content)
            )
        except Exception as e:
            logger.error("Error fetching Gmail attachment", error=str(e))
            return None
    
    def _extract_email_address(self, header: str) -> str:
        """Extract email address from header."""
        if not header:
            return ""
        import re
        match = re.search(r'<([^>]+)>', header)
        if match:
            return match.group(1).lower()
        if "@" in header:
            return header.strip().lower()
        return header.lower()
    
    def _extract_email_addresses(self, header: str) -> List[str]:
        """Extract multiple email addresses from header."""
        if not header:
            return []
        addresses = []
        for addr in header.split(","):
            extracted = self._extract_email_address(addr.strip())
            if extracted:
                addresses.append(extracted)
        return addresses


def get_email_adapter() -> EmailAdapter:
    """Factory function to get the appropriate email adapter."""
    settings = get_settings()
    
    if settings.email_provider.lower() == "gmail":
        return GmailAdapter()
    else:
        return IMAPAdapter()

