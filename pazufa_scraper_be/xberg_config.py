from xberg import ExtractionConfig, OcrConfig, PageConfig


def get_xberg_config(*, ocr: bool) -> ExtractionConfig:
    """Creaate xberg config object."""
    page_config = PageConfig(extract_pages=True)

    if ocr:
        ocr_config = OcrConfig(
            backend="tesseract",
            language=["deu"],
        )
        force_ocr = True

    else:
        ocr_config = None
        force_ocr = False

    return ExtractionConfig(enable_quality_processing=True, pages=page_config, use_cache=False, ocr=ocr_config, force_ocr=force_ocr)
