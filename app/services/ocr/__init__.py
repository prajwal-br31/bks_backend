from .base import OCRProvider, OCRResult
from .tesseract_provider import TesseractProvider
from .factory import get_ocr_provider

__all__ = [
    "OCRProvider",
    "OCRResult",
    "TesseractProvider",
    "get_ocr_provider",
]





