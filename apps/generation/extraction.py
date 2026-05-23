"""Turn any source (link / file / text) into clean text for the LLM."""
import io
import logging

from django.core.files.storage import default_storage

from apps.common.exceptions import GenerationError

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000  # keep prompts (and cost) bounded


def _truncate(text: str) -> str:
    text = (text or "").strip()
    return text[:MAX_TEXT_CHARS]


def extract_from_link(url: str) -> str:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise GenerationError("Could not read that link.")
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if not text:
        raise GenerationError("That page had no readable article content.")
    return _truncate(text)


def extract_from_text(raw: str) -> str:
    return _truncate(raw)


def extract_from_file(file_key: str) -> str:
    if not default_storage.exists(file_key):
        raise GenerationError("Uploaded file could not be found.")
    ext = file_key.rsplit(".", 1)[-1].lower() if "." in file_key else ""
    with default_storage.open(file_key, "rb") as fh:
        blob = fh.read()

    if ext == "pdf":
        return _truncate(_pdf_text(blob))
    if ext in ("doc", "docx"):
        return _truncate(_docx_text(blob))
    if ext in ("png", "jpg", "jpeg"):
        return _truncate(_ocr_text(blob))
    if ext in ("txt", "md"):
        return _truncate(blob.decode("utf-8", errors="ignore"))
    raise GenerationError(f"Unsupported file type: .{ext}")


def _pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(blob: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(blob))
    return "\n".join(p.text for p in doc.paragraphs)


def _ocr_text(blob: bytes) -> str:
    import pytesseract
    from PIL import Image

    return pytesseract.image_to_string(Image.open(io.BytesIO(blob)))


def extract_text(source_kind: str, source_ref: str) -> str:
    if source_kind == "link":
        return extract_from_link(source_ref)
    if source_kind == "text":
        return extract_from_text(source_ref)
    if source_kind == "file":
        return extract_from_file(source_ref)
    raise GenerationError(f"Unknown source kind: {source_kind}")
