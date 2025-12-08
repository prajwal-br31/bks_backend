import logging
from typing import Literal

from app.core.config import get_settings
from .base import EmailAdapter
from .imap_adapter import IMAPAdapter
from .gmail_adapter import GmailAdapter

logger = logging.getLogger(__name__)


def get_email_adapter(provider: Literal["imap", "gmail"] = None) -> EmailAdapter:
    """
    Factory function to get the appropriate email adapter based on configuration.
    
    Args:
        provider: Override the configured provider. If None, uses EMAIL_PROVIDER from config.
    
    Returns:
        EmailAdapter instance configured for the specified provider.
    """
    settings = get_settings()
    provider = provider or settings.email_provider

    if provider == "imap":
        logger.info(f"Creating IMAP adapter for {settings.imap_host}")
        return IMAPAdapter(
            host=settings.imap_host,
            port=settings.imap_port,
            username=settings.imap_username,
            password=settings.imap_password,
            use_ssl=settings.imap_use_ssl,
            folder=settings.imap_folder,
        )
    elif provider == "gmail":
        logger.info("Creating Gmail API adapter")
        return GmailAdapter(
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            refresh_token=settings.gmail_refresh_token,
            label=settings.gmail_label,
        )
    else:
        raise ValueError(f"Unknown email provider: {provider}")


def is_email_whitelisted(email_address: str) -> bool:
    """
    Check if an email address is whitelisted for processing.
    
    Args:
        email_address: The email address to check.
    
    Returns:
        True if the email is whitelisted or no whitelist is configured.
    """
    settings = get_settings()
    
    whitelist_domains = settings.get_whitelist_domains()
    whitelist_addresses = settings.get_whitelist_addresses()
    
    # If no whitelist configured, allow all
    if not whitelist_domains and not whitelist_addresses:
        return True
    
    email_lower = email_address.lower()
    
    # Check exact address match
    if email_lower in whitelist_addresses:
        return True
    
    # Check domain match
    if "@" in email_lower:
        domain = email_lower.split("@")[-1]
        if domain in whitelist_domains:
            return True
    
    return False





