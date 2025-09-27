import asyncio
from kreuzberg import (
    PaddleOCRConfig,
    ExtractionConfig,
    TesseractConfig,
    PSMMode,
    extract_file,
    EasyOCRConfig,
    TesseractConfig,
)
import easyocr
import paddleocr


async def extract(path):
    config = ExtractionConfig(
        force_ocr=True,
        ocr_backend="tesseract",
        ocr_config=TesseractConfig(language="deu"),
    )
    # config = ExtractionConfig(force_ocr=True, ocr_backend="paddleocr", ocr_config=PaddleOCRConfig(language="german"))
    # config = ExtractionConfig(force_ocr=True, ocr_backend="easyocr", ocr_config=EasyOCRConfig(language="de"))
    return await extract_file(path, mime_type="application/pdf", config=config)


# rd = easyocr.Reader(lang_list=["de"], gpu=False)

asyncio.run(extract("0000010263.pdf"))
asyncio.run(extract("0000010213.pdf"))
