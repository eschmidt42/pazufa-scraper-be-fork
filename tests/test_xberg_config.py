from pazufa_scraper_be.xberg_config import get_xberg_config


def test_get_xberg_config_configures_ocr_only_when_requested() -> None:
    """OCR mode enables German Tesseract OCR while default mode disables it."""
    regular_config = get_xberg_config(ocr=False)
    ocr_config = get_xberg_config(ocr=True)

    assert regular_config.pages is not None
    assert regular_config.ocr is None
    assert regular_config.force_ocr is False
    assert regular_config.pages.extract_pages is True
    assert ocr_config.ocr is not None
    assert ocr_config.ocr.backend == "tesseract"
    assert ocr_config.ocr.language == ["deu"]
    assert ocr_config.force_ocr is True
