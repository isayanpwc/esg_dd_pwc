"""
OCR backends, behind an interface.

Scanned pages are common in due diligence — consent orders, older permits and
signed certificates usually arrive as images. Whether OCR is available depends
on the deployment, so this module resolves a backend at call time and, when
none is configured, **fails loudly**.

That choice is deliberate. A silent empty string from an unavailable OCR engine
would mean an image-only page reads as "no disclosure found", which in a due
diligence report is a false negative pointing the wrong way. A missing backend
must therefore surface as an unprocessed page the analyst can see, never as an
empty one.
"""

from esg.config import settings


class OcrUnavailable(RuntimeError):
    """No OCR backend is configured or the configured one is not importable."""


class OcrBackend:
    name = "abstract"

    def image_to_text(self, image_bytes):
        raise NotImplementedError


class TesseractBackend(OcrBackend):
    name = "tesseract"

    def __init__(self):
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            raise OcrUnavailable(
                "ESG_OCR_BACKEND=tesseract but pytesseract/Pillow are not installed. "
                "Install pytesseract and the tesseract binary, or clear "
                "ESG_OCR_BACKEND to leave scanned pages flagged for manual review."
            ) from exc

    def image_to_text(self, image_bytes):
        import io

        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )
        words, confidences = [], []
        for word, confidence in zip(data.get("text", []), data.get("conf", [])):
            if not word.strip():
                continue
            words.append(word)
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confidences.append(value)
        mean_confidence = (sum(confidences) / len(confidences) / 100) if confidences else None
        return " ".join(words), mean_confidence


class NullBackend(OcrBackend):
    """Placeholder used when nothing is configured. Always raises."""

    name = "none"

    def image_to_text(self, image_bytes):
        raise OcrUnavailable(
            "This page contains no extractable text and no OCR backend is "
            "configured (set ESG_OCR_BACKEND=tesseract). The page has been "
            "recorded as image-only and needs manual review — it has not been "
            "treated as empty."
        )


_BACKENDS = {"tesseract": TesseractBackend, "": NullBackend, "none": NullBackend}


def get_backend():
    name = (settings().ocr_backend or "").strip().lower()
    factory = _BACKENDS.get(name)
    if factory is None:
        raise OcrUnavailable(
            f"Unknown ESG_OCR_BACKEND={name!r}. Known: "
            f"{', '.join(k for k in _BACKENDS if k)}"
        )
    return factory()


def available():
    try:
        return not isinstance(get_backend(), NullBackend)
    except OcrUnavailable:
        return False
