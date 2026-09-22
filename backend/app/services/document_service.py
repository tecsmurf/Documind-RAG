"""
Document Processing Service
============================

Pipeline:
    File Upload
         ↓
    Extract Text (PDF, TXT, MD)
         ↓
    Clean Text
         ↓
    Split into Chunks
         ↓
    Generate Embeddings (OpenAI)
         ↓
    Store in pgvector
         ↓
    Mark document as "ready"

Chunking Strategy:
    We split text into overlapping chunks of ~500 tokens.
    Overlap ensures we don't lose context at chunk boundaries.
    
    "The cat sat on the mat. The mat was red."
    Chunk 1: "The cat sat on the mat."
    Chunk 2: "on the mat. The mat was red."  ← overlap
"""
import os
import re
from typing import Optional

from app.core.config import settings


def extract_text_from_file(file_path: str, file_type: str) -> str:
    """Extract raw text from a file."""
    if file_type in ("txt", "md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    elif file_type == "pdf":
        return _extract_pdf(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def _extract_pdf(file_path: str) -> str:
    """Extract text from PDF using PyPDF2."""
    try:
        import PyPDF2
        text_parts = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                text_parts.append(f"[Page {i+1}]\n{page_text}")
        return "\n\n".join(text_parts)
    except ImportError:
        raise ImportError("PyPDF2 is required for PDF processing. Install with: pip install PyPDF2")


def clean_text(text: str) -> str:
    """Clean extracted text — remove extra whitespace, fix encoding issues."""
    # Replace multiple newlines with double newline
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Replace multiple spaces with single space
    text = re.sub(r' {2,}', ' ', text)
    # Remove null bytes
    text = text.replace('\x00', '')
    # Strip leading/trailing whitespace
    text = text.strip()
    return text


def chunk_text(
    text: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> list[dict]:
    """
    Split text into overlapping chunks.
    
    Returns a list of dicts:
    [
        {"content": "chunk text...", "chunk_index": 0, "page_number": 1},
        {"content": "next chunk...", "chunk_index": 1, "page_number": 1},
    ]
    
    Why chunking?
        - LLMs have context windows (limited input size)
        - Embeddings work better on focused text passages
        - Retrieval is more precise with smaller chunks
    
    Why overlap?
        - Prevents losing context at chunk boundaries
        - A sentence split between two chunks would lose meaning
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

    if not text:
        return []

    chunks = []
    # Split by paragraphs first, then recombine to target size
    paragraphs = text.split('\n\n')
    
    current_chunk = ""
    current_page = 1
    chunk_index = 0

    for para in paragraphs:
        # Detect page markers from PDF extraction
        page_match = re.match(r'\[Page (\d+)\]', para)
        if page_match:
            current_page = int(page_match.group(1))
            para = re.sub(r'\[Page \d+\]\n?', '', para).strip()
            if not para:
                continue

        # If adding this paragraph exceeds chunk_size, save current and start new
        if len(current_chunk) + len(para) > chunk_size and current_chunk:
            chunks.append({
                "content": current_chunk.strip(),
                "chunk_index": chunk_index,
                "page_number": current_page,
            })
            chunk_index += 1
            
            # Keep overlap from end of current chunk
            words = current_chunk.split()
            overlap_words = words[-chunk_overlap:] if len(words) > chunk_overlap else words
            current_chunk = " ".join(overlap_words) + "\n\n"
        
        current_chunk += para + "\n\n"
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "content": current_chunk.strip(),
            "chunk_index": chunk_index,
            "page_number": current_page,
        })

    return chunks
