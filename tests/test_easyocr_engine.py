"""Unit tests for EasyOCR bilingual character and digit extraction."""

import os
import numpy as np
import pytest
from PIL import Image

from vision.ocr_engine import OCREngine, OCRResult
from extractors.image_extractor import ocr_image_bytes, ImageExtractor

TEST_IMG_PATH = "HighwaySpeedLimit_3m_768x739.webp"


def test_ocr_engine_available():
    engine = OCREngine()
    assert engine.is_available() is True


def test_ocr_engine_extract_text_characters_and_digits():
    if not os.path.exists(TEST_IMG_PATH):
        pytest.skip(f"Test image {TEST_IMG_PATH} not found")

    engine = OCREngine(use_easyocr=True)
    res = engine.extract_text(TEST_IMG_PATH)
    assert res is not None
    assert isinstance(res, OCRResult)
    assert res.confidence > 0.0

    text = res.text
    # Check English characters
    assert any(w in text.upper() for w in ["SPEED", "HIGHWAY", "EXIT", "LANES", "OBSERVE"])

    # Check Hindi characters
    assert any(w in text for w in ["गति", "हाईवे", "लेन", "निकास", "हवाई अड्डा"])

    # Check digits (either English or Hindi Devanagari numerals)
    assert any(d in text for d in ["15", "१५", "3", "३"])


def test_ocr_engine_extract_from_array():
    if not os.path.exists(TEST_IMG_PATH):
        pytest.skip(f"Test image {TEST_IMG_PATH} not found")

    pil_img = Image.open(TEST_IMG_PATH)
    arr = np.array(pil_img)

    engine = OCREngine(use_easyocr=True)
    res = engine.extract_from_array(arr)
    assert res is not None
    assert "HIGHWAY" in res.text.upper() or "हाईवे" in res.text


def test_ocr_image_bytes_integration():
    if not os.path.exists(TEST_IMG_PATH):
        pytest.skip(f"Test image {TEST_IMG_PATH} not found")

    with open(TEST_IMG_PATH, "rb") as f:
        data = f.read()

    text = ocr_image_bytes(data)
    assert len(text) > 0
    assert any(w in text.upper() for w in ["HIGHWAY", "SPEED", "EXIT"])
    assert any(w in text for w in ["गति", "हाईवे", "लेन"])


def test_image_extractor_produces_ocr_block():
    if not os.path.exists(TEST_IMG_PATH):
        pytest.skip(f"Test image {TEST_IMG_PATH} not found")

    extractor = ImageExtractor()
    blocks = extractor.extract(TEST_IMG_PATH)
    ocr_blocks = [b for b in blocks if b.source_type == "ocr"]
    assert len(ocr_blocks) >= 1
    ocr_text = ocr_blocks[0].text
    assert "HIGHWAY" in ocr_text.upper() or "हाईवे" in ocr_text
