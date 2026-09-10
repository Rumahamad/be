from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal

from app.config.settings import get_settings
from app.engines.payment_verification.hdfc_email_parser import normalize_upi_reference


REFERENCE_LABEL = re.compile(
    r"(?:UPI\s*(?:transaction\s*)?(?:ID|reference|ref(?:erence)?(?:\s*(?:no|number))?)|"
    r"UTR|transaction\s*(?:ID|reference)|reference\s*(?:no|number))",
    re.IGNORECASE,
)
REFERENCE_VALUE = re.compile(r"(?<!\d)(?:\d[\s:\-]*){10,20}(?!\d)")


class OcrUnavailableError(RuntimeError):
    pass


class OcrProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReferenceCandidate:
    value: str
    score: Decimal
    context: str


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: Decimal | None
    candidates: list[ReferenceCandidate]
    selected_reference: str | None
    engine: str
    engine_version: str | None


def extract_reference_candidates(text: str) -> list[ReferenceCandidate]:
    """Extract only numbers close to a transaction-reference label.

    A random long number from the screenshot is intentionally not accepted.
    """
    normalized_text = re.sub(r"[\t\r]+", " ", text or "")
    found: dict[str, ReferenceCandidate] = {}
    for label in REFERENCE_LABEL.finditer(normalized_text):
        window = normalized_text[label.start(): label.end() + 100]
        for match in REFERENCE_VALUE.finditer(window):
            value = normalize_upi_reference(match.group(0))
            if not value:
                continue
            distance = max(0, match.start() - (label.end() - label.start()))
            length_score = Decimal("0.20") if len(value) == 12 else Decimal("0.05")
            distance_score = max(Decimal("0"), Decimal("0.25") - Decimal(distance) / 400)
            score = min(Decimal("0.99"), Decimal("0.55") + length_score + distance_score)
            candidate = ReferenceCandidate(
                value=value,
                score=score.quantize(Decimal("0.0001")),
                context=re.sub(r"\s+", " ", window[:120]).strip(),
            )
            previous = found.get(value)
            if previous is None or candidate.score > previous.score:
                found[value] = candidate
    return sorted(found.values(), key=lambda item: item.score, reverse=True)


class TesseractScreenshotOcr:
    engine = "TESSERACT"

    def extract(self, content: bytes) -> OcrResult:
        try:
            import pytesseract
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
            from pytesseract import Output
        except ImportError as exc:
            raise OcrUnavailableError("Install Pillow and pytesseract") from exc

        settings = get_settings()
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > 20_000_000:
                    raise OcrProcessingError("IMAGE_TOO_LARGE")
                image = ImageOps.exif_transpose(source).convert("L")
                if image.width < 1400:
                    scale = min(1400 / image.width, 4000 / image.height, 3)
                    if scale > 1:
                        image = image.resize((int(image.width * scale), int(image.height * scale)))
                image = ImageOps.autocontrast(image)
                image = ImageEnhance.Contrast(image).enhance(1.4)
                image = image.filter(ImageFilter.SHARPEN)
                data = pytesseract.image_to_data(
                    image,
                    lang=settings.tesseract_language,
                    config="--oem 3 --psm 6",
                    output_type=Output.DICT,
                    timeout=30,
                )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError("Tesseract executable was not found") from exc
        except Exception as exc:
            raise OcrProcessingError(type(exc).__name__) from exc

        words = [str(word).strip() for word in data.get("text", []) if str(word).strip()]
        text = " ".join(words)
        confidences = []
        for raw in data.get("conf", []):
            try:
                value = Decimal(str(raw))
            except Exception:
                continue
            if value >= 0:
                confidences.append(value)
        confidence = None
        if confidences:
            confidence = (sum(confidences) / len(confidences) / 100).quantize(Decimal("0.0001"))
        candidates = extract_reference_candidates(text)
        selected = None
        if candidates and candidates[0].score >= Decimal("0.70"):
            runner_up = candidates[1].score if len(candidates) > 1 else Decimal("0")
            if candidates[0].score - runner_up >= Decimal("0.10"):
                selected = candidates[0].value
        try:
            version = str(pytesseract.get_tesseract_version()).splitlines()[0][:40]
        except Exception:
            version = None
        return OcrResult(text, confidence, candidates, selected, self.engine, version)
