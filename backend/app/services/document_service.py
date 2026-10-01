"""
Document processing (pure functions, no I/O besides parsing bytes)
==================================================================

    validate upload (name, extension, magic bytes, encoding)
         ↓
    extract text per page (pypdf for PDF, UTF-8 for TXT/MD) with limits
         ↓
    clean text
         ↓
    chunk per page (so every chunk has a truthful page number)

Uploaded files are never written to disk: processing works on the bytes in
memory, so a hostile filename can never become a filesystem path. The original
filename is only stored, sanitised, as display metadata.
"""
import io
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = ("pdf", "txt", "md")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_FILENAME_BAD = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
_BINARY_MAGIC = (b"%PDF-", b"PK\x03\x04", b"\x7fELF", b"MZ", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"\x1f\x8b")


class DocumentRejected(Exception):
    """Upload refused before processing; message is safe for users."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ProcessingFailed(Exception):
    """Processing failed; message is safe for users and stored on the document."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class PageText:
    page_number: int | None  # None for TXT/MD (no pages)
    text: str


def sanitize_filename(raw: str | None) -> str:
    """Display-safe filename: no directories, control chars, or reserved characters."""
    name = unicodedata.normalize("NFKC", raw or "")
    name = re.split(r"[\\/]", name)[-1]  # drop any path component, both separators
    name = _FILENAME_BAD.sub("", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else name[:200]
    return name or "document"


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_upload(filename: str, data: bytes) -> str:
    """Check extension *and* content. Returns the verified file type."""
    ext = file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentRejected("Unsupported file type. Upload a PDF, TXT, or MD file.", 415)
    if not data:
        raise DocumentRejected("The file is empty.")
    if len(data) > settings.max_file_size_bytes:
        raise DocumentRejected(f"File is too large. The maximum size is {settings.MAX_FILE_SIZE_MB} MB.", 413)

    if ext == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise DocumentRejected("This file is not a valid PDF.", 415)
        return ext

    # TXT / MD must be real UTF-8 text, not a renamed binary.
    head = data[:16].lstrip(b"\xef\xbb\xbf")
    if head.startswith(_BINARY_MAGIC) or b"\x00" in data:
        raise DocumentRejected("This file does not look like plain text.", 415)
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentRejected("Text files must be UTF-8 encoded.", 415) from None
    return ext


def extract_pages(data: bytes, file_type: str) -> list[PageText]:
    """Extract text with page/char/time limits. Raises ProcessingFailed with safe messages."""
    if file_type in ("txt", "md"):
        text = data.decode("utf-8-sig", errors="replace")
        if len(text) > settings.MAX_EXTRACTED_CHARS:
            raise ProcessingFailed("The document contains too much text to process.")
        return [PageText(None, text)]
    if file_type == "pdf":
        return _extract_pdf(data)
    raise ProcessingFailed("Unsupported file type.")


def _extract_pdf(data: bytes) -> list[PageText]:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    deadline = time.monotonic() + settings.PROCESSING_TIMEOUT_SECONDS / 2
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                # Many PDFs are "encrypted" with an empty user password; anything else is refused.
                if not reader.decrypt(""):
                    raise ProcessingFailed("Password-protected PDFs are not supported.")
            except (FileNotDecryptedError, NotImplementedError):
                raise ProcessingFailed("Password-protected PDFs are not supported.") from None
        page_count = len(reader.pages)
        if page_count == 0:
            raise ProcessingFailed("The PDF has no pages.")
        if page_count > settings.MAX_PDF_PAGES:
            raise ProcessingFailed(f"The PDF has too many pages (maximum {settings.MAX_PDF_PAGES}).")

        pages: list[PageText] = []
        total = 0
        for index, page in enumerate(reader.pages):
            if time.monotonic() > deadline:
                raise ProcessingFailed("The PDF took too long to read.")
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - a single broken page should not sink the document
                logger.warning("Failed to extract page %d", index + 1, exc_info=True)
                text = ""
            total += len(text)
            if total > settings.MAX_EXTRACTED_CHARS:
                raise ProcessingFailed("The document contains too much text to process.")
            pages.append(PageText(index + 1, text))
        return pages
    except ProcessingFailed:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError, OSError):
        logger.info("Unreadable PDF", exc_info=True)
        raise ProcessingFailed("The PDF is damaged or could not be read.") from None
    except MemoryError:
        raise ProcessingFailed("The PDF is too complex to process.") from None
    except Exception:  # noqa: BLE001 - parser bugs on hostile input
        logger.exception("Unexpected PDF parser failure")
        raise ProcessingFailed("The PDF is damaged or could not be read.") from None


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = re.sub(r"[ \t\f\v]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long(text: str, size: int) -> list[str]:
    """Split text longer than `size` at sentence or word boundaries."""
    parts: list[str] = []
    while len(text) > size:
        window = text[:size]
        cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "), window.rfind("\n"))
        if cut < size // 2:
            cut = window.rfind(" ")
        if cut < size // 2:
            cut = size - 1  # no boundary (e.g. one huge token): hard cut
        parts.append(text[: cut + 1].strip())
        text = text[cut + 1 :].lstrip()
    if text.strip():
        parts.append(text.strip())
    return parts


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return "" if overlap <= 0 else text
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def chunk_pages(pages: list[PageText], chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[dict]:
    """
    Pack paragraphs into ~chunk_size character chunks with overlap, never crossing
    a page boundary, so each chunk's page_number is exact (None for TXT/MD).
    """
    size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP
    overlap = min(overlap, size // 2)

    chunks: list[dict] = []
    for page in pages:
        text = clean_text(page.text)
        if not text:
            continue
        pieces: list[str] = []
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                pieces.extend(_split_long(para, size) if len(para) > size else [para])

        current = ""
        has_new = False  # current contains text beyond the carried-over overlap
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > size:
                chunks.append({"content": current, "page_number": page.page_number})
                carry = _overlap_tail(current, overlap)
                current = carry if carry and len(carry) + 2 + len(piece) <= size else ""
                has_new = False
            current = f"{current}\n\n{piece}" if current else piece
            has_new = True
            if len(chunks) > settings.MAX_CHUNKS_PER_DOCUMENT:
                raise ProcessingFailed(
                    f"The document is too large to index (more than {settings.MAX_CHUNKS_PER_DOCUMENT} passages)."
                )
        if current and has_new:
            chunks.append({"content": current, "page_number": page.page_number})

    if len(chunks) > settings.MAX_CHUNKS_PER_DOCUMENT:
        raise ProcessingFailed(
            f"The document is too large to index (more than {settings.MAX_CHUNKS_PER_DOCUMENT} passages)."
        )
    for i, chunk in enumerate(chunks):
        chunk["chunk_index"] = i
    return chunks
