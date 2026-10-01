"""Upload validation, ingestion pipeline, processing states, limits."""
import os
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.database.connection import async_session
from app.models import Chunk, Document
from app.services.document_service import PageText, chunk_pages, sanitize_filename
from app.services.gemini import GeminiError
from tests.helpers import make_pdf, register, upload

LONG_TEXT = "\n\n".join(
    f"Paragraph {i}. The mitochondria is the powerhouse of the cell and section {i} explains energy." for i in range(60)
)


async def chunk_count(doc_id):
    async with async_session() as db:
        return (await db.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id))).scalar_one()


async def test_upload_txt_md_pdf_become_ready(client, fake_gemini):
    h = await register(client, "a@example.com")
    r, doc = await upload(client, h, "notes.txt", LONG_TEXT.encode())
    assert r.status_code == 201 and r.json()["status"] == "processing"
    assert doc["status"] == "ready" and doc["processing_stage"] == "ready"
    assert doc["total_chunks"] > 1 and doc["total_chunks"] == await chunk_count(doc["id"])
    assert doc["error_message"] is None

    _, md = await upload(client, h, "readme.md", b"# Title\n\nSome *markdown* content about vectors.")
    assert md["status"] == "ready" and md["total_chunks"] == 1

    _, pdf = await upload(client, h, "paper.pdf", make_pdf(["First page about apples.", "Second page about pears."]))
    assert pdf["status"] == "ready" and pdf["page_count"] == 2 and pdf["total_chunks"] == 2
    async with async_session() as db:
        pages = (await db.execute(select(Chunk.page_number).where(Chunk.document_id == pdf["id"]).order_by(Chunk.chunk_index))).scalars().all()
        assert pages == [1, 2]
        # every chunk has an embedding of the right size
        embs = (await db.execute(select(Chunk.embedding).where(Chunk.document_id == doc["id"]))).scalars().all()
        assert all(e is not None and len(e) == settings.EMBEDDING_DIMENSIONS for e in embs)
    assert fake_gemini.embed_calls[0][1] == "RETRIEVAL_DOCUMENT"

    listing = (await client.get("/api/documents", headers=h)).json()
    assert {d["filename"] for d in listing} == {"notes.txt", "readme.md", "paper.pdf"}


async def test_rejects_wrong_types_and_spoofed_content(client):
    h = await register(client, "b@example.com")
    cases = [
        ("evil.exe", b"MZ\x90\x00binary", 415),
        ("page.html", b"<script>alert(1)</script>", 415),
        ("noext", b"hello", 415),
        ("fake.pdf", b"just text pretending to be a pdf", 415),
        ("image.txt", b"\x89PNG\r\n\x1a\n\x00\x00binary", 415),
        ("zip.md", b"PK\x03\x04rest-of-zip", 415),
        ("latin1.txt", "caf\xe9".encode("latin-1"), 415),
        ("empty.txt", b"", 400),
    ]
    for name, data, code in cases:
        r, _ = await upload(client, h, name, data)
        assert r.status_code == code, (name, r.text)
    async with async_session() as db:
        assert (await db.execute(select(func.count()).select_from(Document))).scalar_one() == 0


async def test_oversized_upload_rejected_before_processing(client, monkeypatch, fake_gemini):
    h = await register(client, "c@example.com")
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    r, _ = await upload(client, h, "big.txt", b"a" * (1024 * 1024 + 70 * 1024))
    assert r.status_code == 413
    assert fake_gemini.embed_calls == []


async def test_malicious_filenames_are_sanitised_and_never_touch_disk(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = await register(client, "d@example.com")
    names = ["../../secret.txt", "..\\..\\secret.txt", "/etc/passwd.txt", "C:\\Windows\\System32\\x.txt",
             "nul\x00byte.txt", "ctrl\x07\x1b.txt"]
    stored = []
    for i, name in enumerate(names):
        r, doc = await upload(client, h, name, f"unique content {i}".encode())
        assert r.status_code == 201, (name, r.text)
        stored.append(doc["filename"])
    for s in stored:
        assert "/" not in s and "\\" not in s and "\x00" not in s and ".." not in s.split(".txt")[0]
    assert stored[0] == "secret.txt" and stored[3] == "x.txt"
    assert list(Path(tmp_path).rglob("*")) == []  # nothing written to disk
    assert not os.path.exists("/etc/passwd.txt")


def test_sanitize_filename_unit():
    assert sanitize_filename(None) == "document"
    assert sanitize_filename("....") == "document"
    assert sanitize_filename("a/b/c.pdf") == "c.pdf"
    assert len(sanitize_filename("x" * 500 + ".pdf")) <= 200
    assert sanitize_filename("x" * 500 + ".pdf").endswith(".pdf")


async def test_malformed_and_encrypted_pdfs_become_error_with_safe_message(client):
    from pypdf import PdfReader, PdfWriter
    import io

    h = await register(client, "e@example.com")
    _, bad = await upload(client, h, "broken.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog >> garbage \x00\xff")
    assert bad["status"] == "error"
    assert bad["error_message"] == "The PDF is damaged or could not be read."

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["secret page"]))))
    writer.encrypt(user_password="pw", owner_password="owner")
    buf = io.BytesIO()
    writer.write(buf)
    _, enc = await upload(client, h, "locked.pdf", buf.getvalue())
    assert enc["status"] == "error" and "Password-protected" in enc["error_message"]
    assert await chunk_count(enc["id"]) == 0

    _, empty = await upload(client, h, "blank.pdf", make_pdf([""]))
    assert empty["status"] == "error" and "No readable text" in empty["error_message"]


async def test_pdf_page_limit(client, monkeypatch):
    h = await register(client, "f@example.com")
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 3)
    _, doc = await upload(client, h, "long.pdf", make_pdf([f"page {i}" for i in range(5)]))
    assert doc["status"] == "error" and "too many pages" in doc["error_message"]


async def test_chunk_limit(client, monkeypatch):
    h = await register(client, "g@example.com")
    monkeypatch.setattr(settings, "MAX_CHUNKS_PER_DOCUMENT", 3)
    _, doc = await upload(client, h, "huge.txt", LONG_TEXT.encode())
    assert doc["status"] == "error" and "too large to index" in doc["error_message"]
    assert await chunk_count(doc["id"]) == 0


async def test_embedding_failure_marks_error_and_stores_no_chunks(client, fake_gemini):
    h = await register(client, "h@example.com")
    fake_gemini.embed_error = GeminiError("quota", "The AI service is busy or out of quota right now. Please try again in a minute.")
    _, doc = await upload(client, h, "notes.txt", LONG_TEXT.encode())
    assert doc["status"] == "error" and doc["total_chunks"] == 0
    assert doc["error_message"].startswith("Could not create embeddings.")
    assert "429" not in doc["error_message"] and "RESOURCE_EXHAUSTED" not in doc["error_message"]
    assert await chunk_count(doc["id"]) == 0


async def test_unexpected_failure_is_generic(client, fake_gemini):
    h = await register(client, "i@example.com")
    fake_gemini.embed_error = RuntimeError("postgres://user:pw@host/db exploded at /app/secret/path.py")
    _, doc = await upload(client, h, "notes.txt", b"some text here")
    assert doc["status"] == "error"
    assert doc["error_message"] == "Document processing failed. Try uploading the document again."


async def test_duplicate_upload_and_retry_after_error(client, fake_gemini):
    h = await register(client, "j@example.com")
    _, first = await upload(client, h, "a.txt", b"identical content")
    assert first["status"] == "ready"
    r, _ = await upload(client, h, "renamed.txt", b"identical content")
    assert r.status_code == 409

    fake_gemini.embed_error = GeminiError("network", "Could not reach the AI service. Please try again.")
    _, failed = await upload(client, h, "b.txt", b"other content")
    assert failed["status"] == "error"
    fake_gemini.embed_error = None
    _, retried = await upload(client, h, "b.txt", b"other content")
    assert retried["status"] == "ready"
    ids = [d["id"] for d in (await client.get("/api/documents", headers=h)).json()]
    assert failed["id"] not in ids  # the failed entry was replaced, not duplicated


async def test_document_count_limit(client, monkeypatch):
    h = await register(client, "k@example.com")
    monkeypatch.setattr(settings, "MAX_DOCUMENTS_PER_USER", 2)
    for i in range(2):
        r, _ = await upload(client, h, f"{i}.txt", f"doc {i}".encode())
        assert r.status_code == 201
    r, _ = await upload(client, h, "3.txt", b"doc 3")
    assert r.status_code == 400


async def test_upload_rate_limit(client):
    h = await register(client, "l@example.com")
    codes = []
    for i in range(11):
        r, _ = await upload(client, h, f"{i}.txt", f"content {i}".encode(), wait=False)
        codes.append(r.status_code)
    from app.services.ingestion_service import wait_for_ingestions
    await wait_for_ingestions()
    assert codes[:10] == [201] * 10 and codes[10] == 429


async def test_delete_document_removes_chunks(client):
    h = await register(client, "m@example.com")
    _, doc = await upload(client, h, "notes.txt", LONG_TEXT.encode())
    assert await chunk_count(doc["id"]) > 0
    assert (await client.delete(f"/api/documents/{doc['id']}", headers=h)).status_code == 204
    assert await chunk_count(doc["id"]) == 0
    assert (await client.get(f"/api/documents/{doc['id']}", headers=h)).status_code == 404


async def test_stale_processing_documents_are_reaped(client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update

    h = await register(client, "n@example.com")
    _, doc = await upload(client, h, "notes.txt", b"text")
    async with async_session() as db:
        await db.execute(update(Document).where(Document.id == doc["id"]).values(
            status="processing", updated_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        await db.commit()
    listed = (await client.get("/api/documents", headers=h)).json()[0]
    assert listed["status"] == "error" and "interrupted" in listed["error_message"]


def test_chunker_properties():
    pages = [PageText(1, "word " * 2000), PageText(2, ""), PageText(3, "short tail")]
    chunks = chunk_pages(pages, chunk_size=500, chunk_overlap=50)
    assert all(len(c["content"]) <= 500 for c in chunks)
    assert chunks[-1]["page_number"] == 3 and chunks[-1]["content"] == "short tail"
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    # a single unbroken token longer than the chunk size is hard-split, not kept whole
    assert all(len(c["content"]) <= 500 for c in chunk_pages([PageText(None, "x" * 5000)], 500, 0))
    # fake "[Page 99]" markers in text no longer spoof page numbers
    assert chunk_pages([PageText(None, "[Page 99]\nhello")], 500, 0)[0]["page_number"] is None
