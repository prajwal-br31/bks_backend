import logging
from typing import Literal

from app.core.config import get_settings
from .base import OCRProvider
from .tesseract_provider import TesseractProvider

logger = logging.getLogger(__name__)


def get_ocr_provider(provider: Literal["tesseract", "google_vision", "aws_textract"] = None) -> OCRProvider:
    """
    Factory function to get the appropriate OCR provider.
    
    Args:
        provider: Override the configured provider. If None, uses OCR_PROVIDER from config.
    
    Returns:
        OCRProvider instance.
    """
    settings = get_settings()
    provider = provider or settings.ocr_provider

    if provider == "tesseract":
        logger.info("Creating Tesseract OCR provider")
        return TesseractProvider()
    
    elif provider == "google_vision":
        logger.info("Creating Google Cloud Vision OCR provider")
        # Import here to avoid dependency if not used
        try:
            from .google_vision_provider import GoogleVisionProvider
            return GoogleVisionProvider(
                credentials_path=settings.google_cloud_credentials_json
            )
        except ImportError:
            logger.error("Google Cloud Vision provider not available")
            raise ImportError("google-cloud-vision not installed")
    
    elif provider == "aws_textract":
        logger.info("Creating AWS Textract OCR provider")
        try:
            from .aws_textract_provider import AWSTextractProvider
            return AWSTextractProvider(
                access_key=settings.aws_access_key_id,
                secret_key=settings.aws_secret_access_key,
                region=settings.aws_region,
            )
        except ImportError:
            logger.error("AWS Textract provider not available")
            raise ImportError("boto3 not installed")
    
    else:
        raise ValueError(f"Unknown OCR provider: {provider}")





