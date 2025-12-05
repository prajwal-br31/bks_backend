import asyncio
import base64
import logging
from datetime import datetime
from typing import Optional

from .base import EmailAdapter, EmailAttachment, EmailMessage

logger = logging.getLogger(__name__)


class GmailAdapter(EmailAdapter):
    """Gmail API adapter using OAuth2."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        label: str = "INBOX",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.default_label = label
        self._service = None
        self._credentials = None

    async def connect(self) -> None:
        """Establish Gmail API connection."""
        def _connect():
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                
                self._credentials = Credentials(
                    token=None,
                    refresh_token=self.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                )
                
                self._service = build("gmail", "v1", credentials=self._credentials)
                logger.info("Connected to Gmail API")
                return True
            except ImportError:
                logger.error("Google API client not installed. Run: pip install google-api-python-client google-auth")
                raise
            except Exception as e:
                logger.error(f"Failed to connect to Gmail API: {e}")
                raise

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _connect)

    async def disconnect(self) -> None:
        """Close Gmail API connection."""
        self._service = None
        self._credentials = None
        logger.info("Disconnected from Gmail API")

    async def fetch_unread_emails(
        self,
        folder: str = None,
        limit: int = 50,
        since: Optional[datetime] = None,
    ) -> list[EmailMessage]:
        """Fetch unread emails from Gmail."""
        if not self._service:
            raise ConnectionError("Not connected to Gmail API")

        label = folder or self.default_label

        def _fetch():
            # Build query
            query_parts = ["is:unread"]
            if since:
                date_str = since.strftime("%Y/%m/%d")
                query_parts.append(f"after:{date_str}")
            
            query = " ".join(query_parts)
            
            # Get message IDs
            results = self._service.users().messages().list(
                userId="me",
                q=query,
                labelIds=[label] if label != "INBOX" else None,
                maxResults=limit,
            ).execute()
            
            messages = []
            message_ids = results.get("messages", [])
            
            for msg_ref in message_ids:
                try:
                    msg = self._service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full",
                    ).execute()
                    
                    parsed = self._parse_gmail_message(msg)
                    if parsed:
                        messages.append(parsed)
                except Exception as e:
                    logger.error(f"Error fetching Gmail message {msg_ref['id']}: {e}")
                    continue
            
            return messages

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def fetch_email_by_uid(self, uid: str, folder: str = None) -> Optional[EmailMessage]:
        """Fetch a specific email by ID."""
        if not self._service:
            raise ConnectionError("Not connected to Gmail API")

        def _fetch():
            try:
                msg = self._service.users().messages().get(
                    userId="me",
                    id=uid,
                    format="full",
                ).execute()
                return self._parse_gmail_message(msg)
            except Exception as e:
                logger.error(f"Error fetching Gmail message {uid}: {e}")
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def mark_as_read(self, uid: str, folder: str = None) -> bool:
        """Mark email as read."""
        if not self._service:
            raise ConnectionError("Not connected to Gmail API")

        def _mark():
            try:
                self._service.users().messages().modify(
                    userId="me",
                    id=uid,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
                return True
            except Exception as e:
                logger.error(f"Error marking Gmail message {uid} as read: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _mark)

    async def mark_as_processed(self, uid: str, folder: str = None) -> bool:
        """Mark email as processed by adding a label."""
        if not self._service:
            raise ConnectionError("Not connected to Gmail API")

        def _mark():
            try:
                # First, ensure the "Processed" label exists
                label_id = self._get_or_create_label("Processed")
                
                self._service.users().messages().modify(
                    userId="me",
                    id=uid,
                    body={
                        "removeLabelIds": ["UNREAD"],
                        "addLabelIds": [label_id],
                    },
                ).execute()
                return True
            except Exception as e:
                logger.error(f"Error marking Gmail message {uid} as processed: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _mark)

    async def get_folders(self) -> list[str]:
        """Get list of Gmail labels."""
        if not self._service:
            raise ConnectionError("Not connected to Gmail API")

        def _get_labels():
            results = self._service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            return [label["name"] for label in labels]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_labels)

    async def health_check(self) -> bool:
        """Check Gmail API connection health."""
        if not self._service:
            return False

        def _check():
            try:
                self._service.users().getProfile(userId="me").execute()
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    def _get_or_create_label(self, label_name: str) -> str:
        """Get or create a Gmail label."""
        try:
            # List existing labels
            results = self._service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            
            for label in labels:
                if label["name"] == label_name:
                    return label["id"]
            
            # Create new label
            new_label = self._service.users().labels().create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            ).execute()
            return new_label["id"]
        except Exception as e:
            logger.error(f"Error creating label {label_name}: {e}")
            raise

    def _parse_gmail_message(self, msg: dict) -> Optional[EmailMessage]:
        """Parse Gmail API message into EmailMessage dataclass."""
        try:
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            
            # Extract basic info
            message_id = headers.get("Message-ID", f"<{msg['id']}@gmail.com>")
            from_address = self._extract_email(headers.get("From", ""))
            to_header = headers.get("To", "")
            to_addresses = [self._extract_email(addr) for addr in to_header.split(",")]
            subject = headers.get("Subject", "")
            
            # Parse date
            date_str = headers.get("Date")
            try:
                from email.utils import parsedate_to_datetime
                date = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
            except Exception:
                # Try timestamp from Gmail
                timestamp_ms = int(msg.get("internalDate", 0))
                date = datetime.fromtimestamp(timestamp_ms / 1000) if timestamp_ms else datetime.utcnow()
            
            # Get labels
            labels = msg.get("labelIds", [])
            is_read = "UNREAD" not in labels
            
            # Extract body and attachments
            body_text = None
            body_html = None
            attachments = []
            
            payload = msg.get("payload", {})
            self._extract_parts(payload, attachments, msg["id"])
            
            # Get body from payload
            if payload.get("body", {}).get("data"):
                mime_type = payload.get("mimeType", "text/plain")
                body_data = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
                if mime_type == "text/html":
                    body_html = body_data
                else:
                    body_text = body_data
            
            # Extract from parts
            for part in payload.get("parts", []):
                mime_type = part.get("mimeType", "")
                if part.get("body", {}).get("data"):
                    data = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    if mime_type == "text/html" and not body_html:
                        body_html = data
                    elif mime_type == "text/plain" and not body_text:
                        body_text = data

            return EmailMessage(
                uid=msg["id"],
                message_id=message_id,
                from_address=from_address,
                to_addresses=to_addresses,
                subject=subject,
                date=date,
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
                labels=labels,
                is_read=is_read,
                raw_headers=headers,
            )

        except Exception as e:
            logger.error(f"Error parsing Gmail message: {e}")
            return None

    def _extract_parts(self, payload: dict, attachments: list, message_id: str) -> None:
        """Recursively extract attachments from message parts."""
        parts = payload.get("parts", [])
        
        for part in parts:
            # Recurse into nested parts
            if part.get("parts"):
                self._extract_parts(part, attachments, message_id)
            
            # Check for attachment
            filename = part.get("filename")
            if filename and part.get("body", {}).get("attachmentId"):
                try:
                    # Fetch attachment content
                    attachment_data = self._service.users().messages().attachments().get(
                        userId="me",
                        messageId=message_id,
                        id=part["body"]["attachmentId"],
                    ).execute()
                    
                    content = base64.urlsafe_b64decode(attachment_data["data"])
                    
                    attachments.append(EmailAttachment(
                        filename=filename,
                        content_type=part.get("mimeType", "application/octet-stream"),
                        content=content,
                        size=len(content),
                        content_id=part.get("headers", {}).get("Content-ID"),
                    ))
                except Exception as e:
                    logger.error(f"Error fetching attachment {filename}: {e}")

    def _extract_email(self, header: str) -> str:
        """Extract email address from header."""
        if "<" in header and ">" in header:
            start = header.find("<") + 1
            end = header.find(">")
            return header[start:end].strip().lower()
        return header.strip().lower()

