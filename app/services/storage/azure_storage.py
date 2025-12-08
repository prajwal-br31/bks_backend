import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class StoredFile:
    """Represents a stored file in Azure Blob Storage."""
    bucket: str  # Container name
    key: str  # Blob name
    url: str
    content_hash: str
    content_type: str
    size: int
    original_filename: str


class AzureBlobStorageService:
    """
    Azure Blob Storage service for documents.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        account_name: Optional[str] = None,
        account_key: Optional[str] = None,
        container_name: Optional[str] = None,
    ):
        settings = get_settings()
        
        self.connection_string = connection_string or getattr(settings, 'azure_storage_connection_string', None)
        self.account_name = account_name or getattr(settings, 'azure_storage_account_name', None)
        self.account_key = account_key or getattr(settings, 'azure_storage_account_key', None)
        self.container_name = container_name or getattr(settings, 'azure_storage_container_name', 'bookkeeping-documents')
        
        self._client = None

    def _get_client(self):
        """Get or create Azure Blob Storage client."""
        if self._client is None:
            try:
                from azure.storage.blob import BlobServiceClient
                
                if self.connection_string:
                    self._client = BlobServiceClient.from_connection_string(self.connection_string)
                elif self.account_name and self.account_key:
                    account_url = f"https://{self.account_name}.blob.core.windows.net"
                    self._client = BlobServiceClient(account_url=account_url, credential=self.account_key)
                else:
                    raise ValueError(
                        "Azure storage credentials not configured. "
                        "Provide AZURE_STORAGE_CONNECTION_STRING or "
                        "(AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY) in .env file"
                    )
                    
            except ImportError:
                raise ImportError("azure-storage-blob not installed. Run: pip install azure-storage-blob")
        
        return self._client

    async def upload_file(
        self,
        content: bytes,
        original_filename: str,
        content_type: str,
        folder: str = "documents",
        metadata: Optional[dict] = None,
    ) -> StoredFile:
        """
        Upload a file to Azure Blob Storage.
        
        Args:
            content: File content as bytes
            original_filename: Original filename for reference
            content_type: MIME type
            folder: Folder/prefix in container
            metadata: Optional metadata to store with file
        
        Returns:
            StoredFile with storage information
        """
        def _upload():
            client = self._get_client()
            container_client = client.get_container_client(self.container_name)
            
            # Ensure container exists
            try:
                container_client.create_container()
            except Exception:
                pass  # Container already exists
            
            # Generate unique blob name
            content_hash = hashlib.sha256(content).hexdigest()
            ext = Path(original_filename).suffix.lower()
            timestamp = datetime.utcnow().strftime("%Y/%m/%d")
            unique_id = str(uuid.uuid4())[:8]
            
            blob_name = f"{folder}/{timestamp}/{content_hash[:16]}_{unique_id}{ext}"
            
            # Prepare metadata
            blob_metadata = {
                "original_filename": original_filename,
                "content_hash": content_hash,
                "uploaded_at": datetime.utcnow().isoformat(),
            }
            if metadata:
                blob_metadata.update({k: str(v) for k, v in metadata.items()})
            
            # Upload
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(
                data=content,
                content_type=content_type,
                metadata=blob_metadata,
                overwrite=True,
            )
            
            # Generate URL
            url = blob_client.url
            
            return StoredFile(
                bucket=self.container_name,
                key=blob_name,
                url=url,
                content_hash=content_hash,
                content_type=content_type,
                size=len(content),
                original_filename=original_filename,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _upload)

    async def download_file(self, key: str) -> bytes:
        """
        Download a file from Azure Blob Storage.
        
        Args:
            key: Blob name
            
        Returns:
            File content as bytes
        """
        def _download():
            client = self._get_client()
            container_client = client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(key)
            return blob_client.download_blob().readall()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _download)

    async def delete_file(self, key: str) -> bool:
        """
        Delete a file from Azure Blob Storage.
        
        Args:
            key: Blob name
            
        Returns:
            True if deleted successfully
        """
        def _delete():
            try:
                client = self._get_client()
                container_client = client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(key)
                blob_client.delete_blob()
                return True
            except Exception as e:
                logger.error(f"Error deleting file {key}: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _delete)

    async def get_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for temporary access.
        
        Args:
            key: Blob name
            expiration: URL expiration in seconds
            
        Returns:
            Presigned URL
        """
        def _get_url():
            from datetime import timedelta
            client = self._get_client()
            container_client = client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(key)
            
            # Generate SAS token
            from azure.storage.blob import generate_container_sas, ContainerSasPermissions
            from datetime import datetime, timedelta
            
            sas_token = generate_container_sas(
                account_name=self.account_name or client.account_name,
                container_name=self.container_name,
                account_key=self.account_key or client.credential,
                permission=ContainerSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(seconds=expiration),
            )
            
            return f"{blob_client.url}?{sas_token}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_url)

    async def file_exists(self, key: str) -> bool:
        """Check if a file exists in Azure Blob Storage."""
        def _exists():
            try:
                client = self._get_client()
                container_client = client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(key)
                blob_client.get_blob_properties()
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _exists)

    async def ensure_bucket_exists(self) -> bool:
        """Ensure the container exists, create if not."""
        def _ensure():
            try:
                client = self._get_client()
                container_client = client.get_container_client(self.container_name)
                container_client.create_container()
                logger.info(f"Created container: {self.container_name}")
                return True
            except Exception as e:
                # Container might already exist
                if "ContainerAlreadyExists" in str(e):
                    return True
                logger.error(f"Error ensuring container exists: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ensure)

    async def health_check(self) -> bool:
        """Check Azure Blob Storage connection health."""
        def _check():
            try:
                client = self._get_client()
                container_client = client.get_container_client(self.container_name)
                container_client.get_container_properties()
                return True
            except Exception as e:
                logger.error(f"Azure Blob Storage health check failed: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

