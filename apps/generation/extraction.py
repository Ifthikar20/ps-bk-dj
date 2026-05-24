"""Turn any source (link / file / text) into clean text for the LLM."""
import io
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import requests

from django.core.files.storage import default_storage

from apps.common.exceptions import GenerationError

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000  # keep prompts (and cost) bounded
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # cap remote fetches
FETCH_TIMEOUT = 10  # seconds

# Content-types we can read as documents (anything else is treated as HTML).
_DOC_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/png": "png",
    "image/jpeg": "jpg",
}
_DOC_EXTENSIONS = {"pdf", "doc", "docx", "png", "jpg", "jpeg"}


def _truncate(text: str) -> str:
    text = (text or "").strip()
    return text[:MAX_TEXT_CHARS]


def _assert_public_url(url: str) -> None:
    """SSRF guard: reject non-http(s) schemes and private/loopback targets.

    Resolves the host and verifies every resolved IP is globally routable so a
    crafted URL can't reach localhost, link-local cloud metadata
    (169.254.169.254), or internal RFC-1918 hosts.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise GenerationError("Only http(s) links are supported.")
    host = parts.hostname
    if not host:
        raise GenerationError("That link is not a valid URL.")
    try:
        infos = socket.getaddrinfo(host, parts.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise GenerationError("Could not resolve that link.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_private:
            raise GenerationError("That link points to a disallowed address.")


def _ext_from_url(url: str) -> str:
    path = urlsplit(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _download(url: str) -> tuple[bytes, str]:
    """Stream a URL with a size cap. Returns (body, content_type)."""
    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            stream=True,
            headers={"User-Agent": "PlayStudyBot/1.0"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GenerationError(f"Could not read that link: {exc}")

    chunks = bytearray()
    for chunk in resp.iter_content(8192):
        chunks.extend(chunk)
        if len(chunks) > MAX_DOWNLOAD_BYTES:
            resp.close()
            raise GenerationError("That link is too large to process.")
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    return bytes(chunks), content_type


def extract_from_link(url: str) -> str:
    _assert_public_url(url)
    blob, content_type = _download(url)

    # Decide whether this is a document or an HTML page.
    doc_ext = _DOC_CONTENT_TYPES.get(content_type)
    if doc_ext is None and _ext_from_url(url) in _DOC_EXTENSIONS:
        doc_ext = _ext_from_url(url)

    if doc_ext in ("pdf",):
        return _truncate(_pdf_text(blob))
    if doc_ext in ("doc", "docx"):
        return _truncate(_docx_text(blob))
    if doc_ext in ("png", "jpg", "jpeg"):
        return _truncate(_ocr_text(blob))

    # Otherwise treat as an HTML article.
    import trafilatura

    text = trafilatura.extract(
        blob.decode("utf-8", errors="ignore"),
        include_comments=False,
        include_tables=False,
    )
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
