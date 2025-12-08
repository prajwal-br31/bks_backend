from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRResult:
    """Result from OCR processing."""
    text: str
    confidence: float  # 0.0 to 1.0
    language: str = "en"
    word_count: int = 0
    metadata: dict = field(default_factory=dict)
    bounding_boxes: list[dict] = field(default_factory=list)  # For document layout


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @abstractmethod
    async def extract_text(self, image_content: bytes, content_type: str = "image/png") -> OCRResult:
        """
        Extract text from an image.
        
        Args:
            image_content: Binary image content
            content_type: MIME type of the image
        
        Returns:
            OCRResult with extracted text and confidence
        """
        pass

    @abstractmethod
    async def extract_text_from_pdf(self, pdf_content: bytes) -> OCRResult:
        """
        Extract text from a scanned PDF using OCR.
        
        Args:
            pdf_content: Binary PDF content
        
        Returns:
            OCRResult with extracted text and confidence
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the OCR provider is available."""
        pass





