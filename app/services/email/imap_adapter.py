import asyncio
import email
import imaplib
import logging
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional

from .base import EmailAdapter, EmailAttachment, EmailMessage

logger = logging.getLogger(__name__)


class IMAPAdapter(EmailAdapter):
    """IMAP email adapter for generic mail servers."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        folder: str = "INBOX",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.default_folder = folder
        self._connection: Optional[imaplib.IMAP4_SSL | imaplib.IMAP4] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish IMAP connection."""
        def _connect():
            if self.use_ssl:
                conn = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                conn = imaplib.IMAP4(self.host, self.port)
            conn.login(self.username, self.password)
            return conn

        loop = asyncio.get_event_loop()
        self._connection = await loop.run_in_executor(None, _connect)
        logger.info(f"Connected to IMAP server: {self.host}")

    async def disconnect(self) -> None:
        """Close IMAP connection."""
        if self._connection:
            def _disconnect():
                try:
                    self._connection.logout()
                except Exception:
                    pass

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _disconnect)
            self._connection = None
            logger.info("Disconnected from IMAP server")

    async def fetch_unread_emails(
        self,
        folder: str = None,
        limit: int = 50,
        since: Optional[datetime] = None,
    ) -> list[EmailMessage]:
        """Fetch unread emails from IMAP."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        folder = folder or self.default_folder

        def _fetch():
            self._connection.select(folder)
            
            # Build search criteria
            criteria = ["UNSEEN"]
            if since:
                date_str = since.strftime("%d-%b-%Y")
                criteria.append(f'SINCE "{date_str}"')
            
            search_criteria = " ".join(criteria)
            _, message_numbers = self._connection.search(None, search_criteria)
            
            if not message_numbers[0]:
                return []

            email_ids = message_numbers[0].split()[-limit:]  # Get latest N
            messages = []

            for email_id in email_ids:
                try:
                    _, msg_data = self._connection.fetch(email_id, "(RFC822 UID)")
                    
                    # Extract UID
                    uid = None
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            # Parse UID from response
                            if b"UID" in response_part[0]:
                                uid_part = response_part[0].decode()
                                uid_start = uid_part.find("UID") + 4
                                uid_end = uid_part.find(" ", uid_start)
                                if uid_end == -1:
                                    uid_end = uid_part.find(")", uid_start)
                                uid = uid_part[uid_start:uid_end].strip()
                            
                            # Parse email
                            raw_email = response_part[1]
                            msg = email.message_from_bytes(raw_email)
                            parsed = self._parse_email(msg, uid or email_id.decode())
                            if parsed:
                                messages.append(parsed)
                except Exception as e:
                    logger.error(f"Error fetching email {email_id}: {e}")
                    continue

            return messages

        loop = asyncio.get_event_loop()
        async with self._lock:
            return await loop.run_in_executor(None, _fetch)

    async def fetch_email_by_uid(self, uid: str, folder: str = None) -> Optional[EmailMessage]:
        """Fetch a specific email by UID."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        folder = folder or self.default_folder

        def _fetch():
            self._connection.select(folder)
            _, msg_data = self._connection.uid("fetch", uid, "(RFC822)")
            
            if not msg_data or not msg_data[0]:
                return None

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    raw_email = response_part[1]
                    msg = email.message_from_bytes(raw_email)
                    return self._parse_email(msg, uid)
            return None

        loop = asyncio.get_event_loop()
        async with self._lock:
            return await loop.run_in_executor(None, _fetch)

    async def mark_as_read(self, uid: str, folder: str = None) -> bool:
        """Mark email as read."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        folder = folder or self.default_folder

        def _mark():
            self._connection.select(folder)
            self._connection.uid("store", uid, "+FLAGS", "\\Seen")
            return True

        loop = asyncio.get_event_loop()
        async with self._lock:
            try:
                return await loop.run_in_executor(None, _mark)
            except Exception as e:
                logger.error(f"Error marking email {uid} as read: {e}")
                return False

    async def mark_as_processed(self, uid: str, folder: str = None) -> bool:
        """Mark email as processed by adding a flag."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        folder = folder or self.default_folder

        def _mark():
            self._connection.select(folder)
            # Add custom flag to mark as processed
            self._connection.uid("store", uid, "+FLAGS", "\\Seen $Processed")
            return True

        loop = asyncio.get_event_loop()
        async with self._lock:
            try:
                return await loop.run_in_executor(None, _mark)
            except Exception as e:
                logger.error(f"Error marking email {uid} as processed: {e}")
                return False

    async def get_folders(self) -> list[str]:
        """Get list of IMAP folders."""
        if not self._connection:
            raise ConnectionError("Not connected to IMAP server")

        def _get_folders():
            _, folder_list = self._connection.list()
            folders = []
            for folder_data in folder_list:
                if isinstance(folder_data, bytes):
                    # Parse folder name
                    parts = folder_data.decode().split(' "/" ')
                    if len(parts) >= 2:
                        folders.append(parts[-1].strip('"'))
            return folders

        loop = asyncio.get_event_loop()
        async with self._lock:
            return await loop.run_in_executor(None, _get_folders)

    async def health_check(self) -> bool:
        """Check IMAP connection health."""
        if not self._connection:
            return False

        def _check():
            try:
                self._connection.noop()
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    def _parse_email(self, msg: email.message.Message, uid: str) -> Optional[EmailMessage]:
        """Parse an email message into EmailMessage dataclass."""
        try:
            # Decode subject
            subject = self._decode_header(msg.get("Subject", ""))
            
            # Parse from address
            from_header = msg.get("From", "")
            from_address = self._extract_email(from_header)
            
            # Parse to addresses
            to_header = msg.get("To", "")
            to_addresses = [self._extract_email(addr) for addr in to_header.split(",")]
            
            # Parse date
            date_str = msg.get("Date")
            try:
                date = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
            except Exception:
                date = datetime.utcnow()
            
            # Get message ID
            message_id = msg.get("Message-ID", f"<{uid}@local>")
            
            # Extract body and attachments
            body_text = None
            body_html = None
            attachments = []
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))
                    
                    # Handle attachments
                    if "attachment" in content_disposition or part.get_filename():
                        attachment = self._extract_attachment(part)
                        if attachment:
                            attachments.append(attachment)
                    # Handle body
                    elif content_type == "text/plain" and not body_text:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_text = payload.decode(charset, errors="replace")
                    elif content_type == "text/html" and not body_html:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_html = payload.decode(charset, errors="replace")
                    # Handle inline images
                    elif content_type.startswith("image/") and "inline" in content_disposition:
                        attachment = self._extract_attachment(part)
                        if attachment:
                            attachments.append(attachment)
            else:
                # Single part message
                content_type = msg.get_content_type()
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    if content_type == "text/html":
                        body_html = payload.decode(charset, errors="replace")
                    else:
                        body_text = payload.decode(charset, errors="replace")

            return EmailMessage(
                uid=uid,
                message_id=message_id,
                from_address=from_address,
                to_addresses=to_addresses,
                subject=subject,
                date=date,
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
                raw_headers=dict(msg.items()),
            )

        except Exception as e:
            logger.error(f"Error parsing email: {e}")
            return None

    def _decode_header(self, header: str) -> str:
        """Decode email header."""
        if not header:
            return ""
        decoded_parts = decode_header(header)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _extract_email(self, header: str) -> str:
        """Extract email address from header."""
        if "<" in header and ">" in header:
            start = header.find("<") + 1
            end = header.find(">")
            return header[start:end].strip().lower()
        return header.strip().lower()

    def _extract_attachment(self, part: email.message.Message) -> Optional[EmailAttachment]:
        """Extract attachment from email part."""
        try:
            filename = part.get_filename()
            if filename:
                filename = self._decode_header(filename)
            else:
                # Generate filename for inline content
                content_type = part.get_content_type()
                ext = content_type.split("/")[-1] if "/" in content_type else "bin"
                filename = f"attachment.{ext}"

            content = part.get_payload(decode=True)
            if not content:
                return None

            content_type = part.get_content_type()
            content_id = part.get("Content-ID", "").strip("<>")

            return EmailAttachment(
                filename=filename,
                content_type=content_type,
                content=content,
                size=len(content),
                content_id=content_id or None,
            )
        except Exception as e:
            logger.error(f"Error extracting attachment: {e}")
            return None





