"""
Resume text extraction — supports PDF, TXT, and MD files.
"""

import io


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from an uploaded resume file."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(file_bytes)
    elif ext in ("txt", "md", "text"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Upload a PDF, TXT, or MD file.")


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber is required for PDF parsing. Install it: pip install pdfplumber"
        )

    pages_text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    if not pages_text:
        raise ValueError("Could not extract text from this PDF. Try uploading a TXT version instead.")

    return "\n\n".join(pages_text)
