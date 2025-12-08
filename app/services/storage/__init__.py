import logging
from .s3_storage import S3StorageService, StoredFile
from .azure_storage import AzureBlobStorageService

__all__ = [
    "S3StorageService",
    "AzureBlobStorageService",
    "StoredFile",
    "get_storage_service",
]

logger = logging.getLogger(__name__)


def get_storage_service():
    """
    Get the appropriate storage service based on configuration.
    
    Returns:
        Storage service instance (AzureBlobStorageService or S3StorageService)
        
    Raises:
        ValueError: If storage credentials are not configured
    """
    from app.core.config import get_settings
    settings = get_settings()
    
    if settings.storage_provider == "azure_blob":
        try:
            return AzureBlobStorageService()
        except ValueError as e:
            logger.error(f"Azure Blob Storage not configured: {e}")
            raise ValueError(
                "Azure Blob Storage credentials not configured. "
                "Please set AZURE_STORAGE_CONNECTION_STRING or "
                "(AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY) in your .env file"
            ) from e
    elif settings.storage_provider == "s3_compatible":
        return S3StorageService()
    else:
        # Default to Azure if not specified
        try:
            return AzureBlobStorageService()
        except ValueError as e:
            logger.error(f"Storage not configured: {e}")
            raise ValueError(
                "Storage credentials not configured. "
                "Please set STORAGE_PROVIDER and appropriate credentials in your .env file"
            ) from e



