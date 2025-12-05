"""S3-compatible object storage service."""

import io
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, BinaryIO
import structlog

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..core.config import get_settings

logger = structlog.get_logger()


@dataclass
class StorageResult:
    """Result of storage operation."""
    success: bool
    bucket: str
    key: str
    url: Optional[str] = None
    error: Optional[str] = None


class StorageService:
    """S3-compatible storage service."""
    
    def __init__(self):
        self.settings = get_settings()
        self._client = None
    
    @property
    def client(self):
        """Lazy-initialize S3 client."""
        if self._client is None:
            self._client = boto3.client(
                's3',
                endpoint_url=self.settings.s3_endpoint_url,
                aws_access_key_id=self.settings.s3_access_key,
                aws_secret_access_key=self.settings.s3_secret_key,
                region_name=self.settings.s3_region,
                config=Config(signature_version='s3v4')
            )
        return self._client
    
    def ensure_bucket_exists(self) -> bool:
        """Ensure the storage bucket exists."""
        try:
            self.client.head_bucket(Bucket=self.settings.s3_bucket_name)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                try:
                    self.client.create_bucket(
                        Bucket=self.settings.s3_bucket_name
                    )
                    logger.info(
                        "Created storage bucket",
                        bucket=self.settings.s3_bucket_name
                    )
                    return True
                except Exception as create_error:
                    logger.error(
                        "Failed to create bucket",
                        error=str(create_error)
                    )
                    return False
            logger.error("Bucket check failed", error=str(e))
            return False
    
    def upload_file(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        file_hash: str,
        metadata: Optional[dict] = None
    ) -> StorageResult:
        """Upload file to storage."""
        try:
            # Generate unique key with organization
            date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
            unique_id = str(uuid.uuid4())[:8]
            safe_filename = self._sanitize_filename(filename)
            
            key = f"documents/{date_prefix}/{unique_id}_{safe_filename}"
            
            # Prepare metadata
            s3_metadata = {
                'original-filename': filename,
                'file-hash': file_hash,
            }
            if metadata:
                for k, v in metadata.items():
                    s3_metadata[k] = str(v)
            
            # Upload
            self.client.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata=s3_metadata
            )
            
            # Generate URL
            url = self._generate_url(key)
            
            logger.info(
                "File uploaded to storage",
                bucket=self.settings.s3_bucket_name,
                key=key
            )
            
            return StorageResult(
                success=True,
                bucket=self.settings.s3_bucket_name,
                key=key,
                url=url
            )
            
        except Exception as e:
            logger.error("Storage upload failed", error=str(e))
            return StorageResult(
                success=False,
                bucket=self.settings.s3_bucket_name,
                key="",
                error=str(e)
            )
    
    def download_file(self, key: str) -> Optional[bytes]:
        """Download file from storage."""
        try:
            response = self.client.get_object(
                Bucket=self.settings.s3_bucket_name,
                Key=key
            )
            return response['Body'].read()
        except Exception as e:
            logger.error("Storage download failed", key=key, error=str(e))
            return None
    
    def delete_file(self, key: str) -> bool:
        """Delete file from storage."""
        try:
            self.client.delete_object(
                Bucket=self.settings.s3_bucket_name,
                Key=key
            )
            logger.info("File deleted from storage", key=key)
            return True
        except Exception as e:
            logger.error("Storage delete failed", key=key, error=str(e))
            return False
    
    def get_presigned_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Generate a presigned URL for temporary access."""
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.settings.s3_bucket_name,
                    'Key': key
                },
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error("Failed to generate presigned URL", key=key, error=str(e))
            return None
    
    def _generate_url(self, key: str) -> str:
        """Generate storage URL for the object."""
        # For MinIO/local development
        return f"{self.settings.s3_endpoint_url}/{self.settings.s3_bucket_name}/{key}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for storage."""
        # Remove path separators
        filename = filename.replace('/', '_').replace('\\', '_')
        
        # Remove special characters
        safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')
        filename = ''.join(c if c in safe_chars else '_' for c in filename)
        
        # Ensure reasonable length
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[:200-len(ext)] + ext
        
        return filename

