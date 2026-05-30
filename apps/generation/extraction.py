"""Turn any source (link / file / text) into clean text for the LLM."""
import io
import ipaddress
import logging
import re
import socket
from urllib.parse import parse_qs, urlsplit

import requests

from django.conf import settings
from django.core.files.storage import default_storage

from apps.common.exceptions import GenerationError

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000  # keep prompts (and cost) bounded
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # cap remote fetches
FETCH_TIMEOUT = 10  # seconds

# Fixed allow-list of YouTube hostnames. Anything else gets the regular
# SSRF guard + download path so we never bypass safety on look-alike hosts.
_YT_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

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


def _youtube_id(url: str) -> str | None:
    """Return the 11-char video id if [url] points at YouTube, else None.

    Only accepts hostnames in the fixed allow-list above so a malicious
    look-alike (e.g. youtube.com.attacker.tld) can never reach the YouTube
    path — those flow through the regular SSRF-guarded download instead.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host not in _YT_HOSTS:
        return None
    if host == "youtu.be":
        candidate = parts.path.lstrip("/").split("/", 1)[0]
    else:
        # /watch?v=ID, /shorts/ID, /embed/ID, /v/ID
        path = parts.path or ""
        candidate = None
        for prefix in ("/shorts/", "/embed/", "/v/", "/live/"):
            if path.startswith(prefix):
                candidate = path[len(prefix):].split("/", 1)[0]
                break
        if candidate is None:
            qs = parse_qs(parts.query or "")
            candidate = (qs.get("v") or [None])[0]
    return candidate if candidate and _YT_ID_RE.match(candidate) else None


def _youtube_title(video_id: str) -> str | None:
    """Resolve a friendly title via YouTube's public oEmbed endpoint.

    Best-effort: returns None on any failure (the caller falls back to a
    title derived by the LLM from the transcript).
    """
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "PlayStudyBot/1.0"},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        title = (data.get("title") or "").strip()
        return title[:200] if title else None
    except Exception as exc:  # network / json / etc — title is optional
        logger.info("YouTube oembed title lookup failed for %s: %s", video_id, exc)
        return None


def _youtube_text(video_id: str) -> str:
    """Fetch the transcript for [video_id] via yt-dlp and join to plain text.

    yt-dlp writes the subtitle file to a temp dir using its own session
    (the caption URLs YouTube returns are session-bound, so naive HTTP
    GETs of them tend to fail). We then read and parse the file.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise GenerationError(
            "YouTube ingest is not configured on this server."
        ) from exc

    import glob
    import os
    import tempfile

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="ps-yt-") as tmpdir:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            # Accept English first; broaden to any language as a fallback.
            "subtitleslangs": [
                "en", "en-US", "en-GB", "en-AU", "en-CA", "en.*",
                "a.en", "en-orig",
            ],
            "subtitlesformat": "vtt/srv3/json3/best",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": FETCH_TIMEOUT,
            "retries": 2,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # download=True is what triggers the subtitle file write;
                # the actual video is still skipped via skip_download=True.
                ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "private" in msg or "unavailable" in msg or "removed" in msg:
                raise GenerationError(
                    "That YouTube video is unavailable (private, removed, "
                    "or region-locked)."
                ) from exc
            logger.warning("YouTube yt-dlp DownloadError for %s: %s",
                           video_id, exc)
            raise GenerationError(
                "Couldn't read that YouTube video. Try a different link."
            ) from exc
        except Exception as exc:
            logger.warning("YouTube yt-dlp error for %s: %s", video_id, exc)
            raise GenerationError(
                "Couldn't read that YouTube video. Try a different link."
            ) from exc

        # Discover the file yt-dlp actually wrote. Prefer .vtt, then srv*,
        # then json3, then anything.
        path = _pick_caption_file(tmpdir, video_id)
        if path is None:
            raise GenerationError(
                "This YouTube video has no English captions. "
                "Try a different video that has subtitles enabled."
            )
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                body = f.read()
        except OSError as exc:
            logger.warning("Reading caption file failed for %s: %s",
                           video_id, exc)
            raise GenerationError(
                "Couldn't load the captions for that YouTube video."
            ) from exc

    text = _captions_to_text(body)
    if not text.strip():
        raise GenerationError("This YouTube video's captions are empty.")
    return text


def _pick_caption_file(tmpdir: str, video_id: str) -> str | None:
    """Return the path to the most useful subtitle file yt-dlp wrote.

    yt-dlp names them like '<id>.<lang>.<ext>'. Pick by extension
    preference, then by language preference.
    """
    import glob
    import os

    files = glob.glob(os.path.join(tmpdir, f"{video_id}.*"))
    if not files:
        return None
    pref_exts = ("vtt", "srv3", "srv2", "srv1", "json3")
    pref_langs = ("en", "en-US", "en-GB", "en-AU", "en-CA",
                  "en-orig", "a.en")

    def rank(p: str) -> tuple:
        name = os.path.basename(p)
        ext = name.rsplit(".", 1)[-1].lower()
        mid = name[len(video_id) + 1: -(len(ext) + 1)] or ""
        ext_rank = pref_exts.index(ext) if ext in pref_exts else len(pref_exts)
        lang_rank = (pref_langs.index(mid) if mid in pref_langs
                     else len(pref_langs))
        return (lang_rank, ext_rank)

    files.sort(key=rank)
    return files[0]


def _captions_to_text(body: str) -> str:
    """Parse VTT or YouTube srv3/json3 caption body into plain text.

    Strips timestamps, cue settings, and noise markers like [Music].
    """
    body = (body or "").strip()
    if not body:
        return ""
    # JSON3 (yt-dlp's preferred fallback when VTT is unavailable).
    if body.startswith("{"):
        try:
            import json
            data = json.loads(body)
            parts = []
            for event in data.get("events") or []:
                for seg in event.get("segs") or []:
                    s = (seg.get("utf8") or "").strip()
                    if s and s not in ("[Music]", "[Applause]"):
                        parts.append(s)
            return " ".join(parts)
        except Exception:
            return ""
    # VTT (default).
    lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or \
                line.startswith("Language:") or line.startswith("NOTE"):
            continue
        if "-->" in line:  # timing line
            continue
        if line.isdigit():  # cue index
            continue
        # Strip inline tags like <c.colorE5E5E5> and <00:00:01.234>
        line = re.sub(r"<[^>]+>", "", line)
        if line in ("[Music]", "[Applause]"):
            continue
        lines.append(line)
    return " ".join(lines)


def extract_from_link(url: str) -> str:
    # YouTube path runs before the SSRF guard / download, because the public
    # YouTube API does the network for us. We still re-validate the host
    # against a fixed allow-list inside _youtube_id().
    if getattr(settings, "ENABLE_YOUTUBE_INGEST", True):
        if (video_id := _youtube_id(url)):
            return _truncate(_youtube_text(video_id))

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
