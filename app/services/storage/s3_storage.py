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
    """Represents a stored file in S3."""
    bucket: str
    key: str
    url: str
    content_hash: str
    content_type: str
    size: int
    original_filename: str


class S3StorageService:
    """
    S3-compatible storage service for documents.
    
    Supports:
    - AWS S3
    - MinIO
    - DigitalOcean Spaces
    - Any S3-compatible storage
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        settings = get_settings()
        
        self.endpoint_url = endpoint_url or settings.s3_endpoint_url
        self.access_key = access_key or settings.s3_access_key
        self.secret_key = secret_key or settings.s3_secret_key
        self.bucket_name = bucket_name or settings.s3_bucket_name
        self.region = region or settings.s3_region
        
        self._client = None

    def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
                
                config = Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 3, 'mode': 'adaptive'}
                )
                
                self._client = boto3.client(
                    's3',
                    endpoint_url=self.endpoint_url if self.endpoint_url != "https://s3.amazonaws.com" else None,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region,
                    config=config,
                )
            except ImportError:
                raise ImportError("boto3 not installed. Run: pip install boto3")
        
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
        Upload a file to S3.
        
        Args:
            content: File content as bytes
            original_filename: Original filename for reference
            content_type: MIME type
            folder: Folder/prefix in bucket
            metadata: Optional metadata to store with file
        
        Returns:
            StoredFile with storage information
        """
        def _upload():
            client = self._get_client()
            
            # Generate unique key
            content_hash = hashlib.sha256(content).hexdigest()
            ext = Path(original_filename).suffix.lower()
            timestamp = datetime.utcnow().strftime("%Y/%m/%d")
            unique_id = str(uuid.uuid4())[:8]
            
            key = f"{folder}/{timestamp}/{content_hash[:16]}_{unique_id}{ext}"
            
            # Prepare metadata
            file_metadata = {
                "original-filename": original_filename,
                "content-hash": content_hash,
                "uploaded-at": datetime.utcnow().isoformat(),
            }
            if metadata:
                file_metadata.update({k: str(v) for k, v in metadata.items()})
            
            # Upload
            client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata=file_metadata,
            )
            
            # Generate URL
            url = f"s3://{self.bucket_name}/{key}"
            
            return StoredFile(
                bucket=self.bucket_name,
                key=key,
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
        Download a file from S3.
        
        Args:
            key: S3 object key
        
        Returns:
            File content as bytes
        """
        def _download():
            client = self._get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _download)

    async def delete_file(self, key: str) -> bool:
        """
        Delete a file from S3.
        
        Args:
            key: S3 object key
        
        Returns:
            True if deleted successfully
        """
        def _delete():
            try:
                client = self._get_client()
                client.delete_object(Bucket=self.bucket_name, Key=key)
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
            key: S3 object key
            expiration: URL expiration in seconds
        
        Returns:
            Presigned URL
        """
        def _get_url():
            client = self._get_client()
            return client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_url)

    async def file_exists(self, key: str) -> bool:
        """Check if a file exists in S3."""
        def _exists():
            try:
                client = self._get_client()
                client.head_object(Bucket=self.bucket_name, Key=key)
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _exists)

    async def ensure_bucket_exists(self) -> bool:
        """Ensure the bucket exists, create if not."""
        def _ensure():
            try:
                client = self._get_client()
                
                # Check if bucket exists
                try:
                    client.head_bucket(Bucket=self.bucket_name)
                    return True
                except Exception:
                    pass
                
                # Create bucket
                if self.region and self.region != "us-east-1":
                    client.create_bucket(
                        Bucket=self.bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': self.region}
                    )
                else:
                    client.create_bucket(Bucket=self.bucket_name)
                
                logger.info(f"Created bucket: {self.bucket_name}")
                return True
            except Exception as e:
                logger.error(f"Error ensuring bucket exists: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ensure)

    async def health_check(self) -> bool:
        """Check S3 connection health."""
        def _check():
            try:
                client = self._get_client()
                client.list_buckets()
                return True
            except Exception as e:
                logger.error(f"S3 health check failed: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)





