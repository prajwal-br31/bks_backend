from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    project_name: str = "Bash Bookkeeping API"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/bash"
    
    # OpenAI
    openai_api_key: str | None = None

    # ============================================
    # EMAIL INGESTION
    # ============================================
    email_provider: Literal["imap", "gmail"] = "imap"

    # IMAP Configuration
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_folder: str = "INBOX"

    # Gmail API Configuration
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_label: str = "invoices"

    # Email Polling Settings
    email_poll_interval_seconds: int = 30
    email_whitelist_domains: str = ""  # Comma-separated
    email_whitelist_addresses: str = ""  # Comma-separated

    # ============================================
    # OCR
    # ============================================
    ocr_provider: Literal["tesseract", "google_vision", "aws_textract"] = "tesseract"
    google_cloud_credentials_json: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # ============================================
    # OBJECT STORAGE (S3-Compatible)
    # ============================================
    s3_endpoint_url: str = "https://s3.amazonaws.com"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_name: str = "bookkeeping-documents"
    s3_region: str = "us-east-1"

    # ============================================
    # REDIS + CELERY
    # ============================================
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # ============================================
    # SECURITY
    # ============================================
    virus_scanner: Literal["clamav", "none"] = "clamav"
    clamav_host: str = "localhost"
    clamav_port: int = 3310

    # ============================================
    # CLASSIFICATION
    # ============================================
    classification_confidence_threshold: float = 0.75
    auto_post_mode: bool = False

    # ============================================
    # WEBSOCKET
    # ============================================
    websocket_enabled: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    # Helper methods
    def get_whitelist_domains(self) -> list[str]:
        """Return whitelist domains as a list."""
        if not self.email_whitelist_domains:
            return []
        return [d.strip().lower() for d in self.email_whitelist_domains.split(",") if d.strip()]

    def get_whitelist_addresses(self) -> list[str]:
        """Return whitelist addresses as a list."""
        if not self.email_whitelist_addresses:
            return []
        return [a.strip().lower() for a in self.email_whitelist_addresses.split(",") if a.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
