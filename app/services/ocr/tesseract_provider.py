import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from .base import OCRProvider, OCRResult

logger = logging.getLogger(__name__)


class TesseractProvider(OCRProvider):
    """
    Tesseract OCR provider for local text extraction.
    
    Requires:
    - Tesseract installed on the system (tesseract-ocr)
    - pytesseract Python package
    - Pillow for image handling
    - pdf2image for PDF conversion (requires poppler)
    """

    def __init__(self, language: str = "eng", tesseract_cmd: Optional[str] = None):
        """
        Initialize Tesseract provider.
        
        Args:
            language: Tesseract language code (e.g., "eng", "fra", "deu")
            tesseract_cmd: Path to tesseract executable (if not in PATH)
        """
        self.language = language
        self.tesseract_cmd = tesseract_cmd
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure pytesseract is configured."""
        if self._initialized:
            return
        
        try:
            import pytesseract
            
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            
            self._initialized = True
        except ImportError:
            raise ImportError("pytesseract not installed. Run: pip install pytesseract")

    async def extract_text(self, image_content: bytes, content_type: str = "image/png") -> OCRResult:
        """Extract text from an image using Tesseract."""
        def _extract():
            try:
                import pytesseract
                from PIL import Image
                
                self._ensure_initialized()
                
                # Load image
                image = Image.open(io.BytesIO(image_content))
                
                # Preprocess image for better OCR
                image = self._preprocess_image(image)
                
                # Run OCR with detailed output
                data = pytesseract.image_to_data(image, lang=self.language, output_type=pytesseract.Output.DICT)
                
                # Extract text and calculate confidence
                texts = []
                confidences = []
                word_boxes = []
                
                for i, text in enumerate(data["text"]):
                    conf = int(data["conf"][i])
                    if conf > 0 and text.strip():  # Filter out low-confidence and empty
                        texts.append(text)
                        confidences.append(conf)
                        word_boxes.append({
                            "text": text,
                            "confidence": conf,
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                        })
                
                full_text = " ".join(texts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                
                return OCRResult(
                    text=full_text,
                    confidence=avg_confidence / 100,  # Convert to 0-1 scale
                    language=self.language,
                    word_count=len(texts),
                    bounding_boxes=word_boxes,
                    metadata={
                        "provider": "tesseract",
                        "image_size": image.size,
                        "image_mode": image.mode,
                    },
                )
            except ImportError as e:
                logger.error(f"Missing dependency: {e}")
                return OCRResult(text="", confidence=0, metadata={"error": str(e)})
            except Exception as e:
                logger.error(f"OCR error: {e}")
                return OCRResult(text="", confidence=0, metadata={"error": str(e)})

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract)

    async def extract_text_from_pdf(self, pdf_content: bytes) -> OCRResult:
        """Extract text from a scanned PDF using OCR."""
        def _extract():
            try:
                import pytesseract
                from pdf2image import convert_from_bytes
                
                self._ensure_initialized()
                
                # Convert PDF pages to images
                images = convert_from_bytes(pdf_content, dpi=300)
                
                all_texts = []
                all_confidences = []
                page_results = []
                
                for page_num, image in enumerate(images, 1):
                    # Preprocess
                    image = self._preprocess_image(image)
                    
                    # OCR
                    data = pytesseract.image_to_data(image, lang=self.language, output_type=pytesseract.Output.DICT)
                    
                    page_texts = []
                    page_confs = []
                    
                    for i, text in enumerate(data["text"]):
                        conf = int(data["conf"][i])
                        if conf > 0 and text.strip():
                            page_texts.append(text)
                            page_confs.append(conf)
                    
                    page_text = " ".join(page_texts)
                    all_texts.append(page_text)
                    all_confidences.extend(page_confs)
                    
                    page_results.append({
                        "page": page_num,
                        "text": page_text,
                        "word_count": len(page_texts),
                        "avg_confidence": sum(page_confs) / len(page_confs) if page_confs else 0,
                    })
                
                full_text = "\n\n".join(all_texts)
                avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0
                
                return OCRResult(
                    text=full_text,
                    confidence=avg_confidence / 100,
                    language=self.language,
                    word_count=len(full_text.split()),
                    metadata={
                        "provider": "tesseract",
                        "page_count": len(images),
                        "pages": page_results,
                    },
                )
            except ImportError as e:
                logger.error(f"Missing dependency: {e}")
                return OCRResult(text="", confidence=0, metadata={"error": str(e)})
            except Exception as e:
                logger.error(f"PDF OCR error: {e}")
                return OCRResult(text="", confidence=0, metadata={"error": str(e)})

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract)

    async def health_check(self) -> bool:
        """Check if Tesseract is available."""
        def _check():
            try:
                import pytesseract
                self._ensure_initialized()
                
                # Try to get Tesseract version
                version = pytesseract.get_tesseract_version()
                logger.info(f"Tesseract version: {version}")
                return True
            except Exception as e:
                logger.error(f"Tesseract health check failed: {e}")
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    def _preprocess_image(self, image):
        """Preprocess image for better OCR results."""
        from PIL import Image, ImageEnhance, ImageFilter
        
        # Convert to grayscale if not already
        if image.mode != "L":
            image = image.convert("L")
        
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.5)
        
        # Sharpen
        image = image.filter(ImageFilter.SHARPEN)
        
        # Binarize (threshold)
        threshold = 150
        image = image.point(lambda p: 255 if p > threshold else 0)
        
        return image





