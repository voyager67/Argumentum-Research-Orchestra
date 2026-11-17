"""Safe, bounded ingestion of researcher-provided text materials."""

from __future__ import annotations

import csv
import hashlib
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from itertools import islice
from pathlib import Path

from .models import InputDocument

SUPPORTED_TEXT = {".md", ".markdown", ".txt", ".csv", ".json", ".bib", ".tex"}
OPTIONAL_DOCUMENTS = {".pdf", ".docx"}
MAX_FILES = 100
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_GROBID_RESPONSE_BYTES = 30 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 100_000
MAX_PDF_PAGES = 500
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCX_MEMBERS = 10_000
MAX_CSV_PREVIEW_FILES = 20
MAX_CSV_SCAN_ROWS = 500
MAX_CSV_PREVIEW_ROWS = 5
MAX_CSV_COLUMNS = 40
MAX_CSV_CELL_CHARS = 300


class GrobidError(RuntimeError):
    """A configured GROBID service could not extract a PDF."""


def _extract_grobid(path: Path, base_url: str, timeout_seconds: int = 180) -> str:
    """Extract a PDF through GROBID's documented multipart full-text endpoint."""
    if not base_url.startswith(("http://", "https://")):
        raise GrobidError("GROBID URL must use http:// or https://")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise GrobidError("PDF exceeds the configured per-file size limit")
    boundary = f"argumentum-{uuid.uuid4().hex}"
    filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    pdf_bytes = path.read_bytes()
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="input"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/processFulltextDocument",
        data=prefix + pdf_bytes + suffix,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/xml"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(MAX_GROBID_RESPONSE_BYTES + 1)
        if len(payload) > MAX_GROBID_RESPONSE_BYTES:
            raise GrobidError("GROBID response exceeded the configured size limit")
        if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
            raise GrobidError("GROBID returned XML with a prohibited document type or entity declaration")
        if not payload.strip():
            raise GrobidError("GROBID returned an empty extraction")
        root = ET.fromstring(payload)
    except urllib.error.HTTPError as exc:
        raise GrobidError(f"GROBID returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GrobidError(f"GROBID request failed: {type(exc).__name__}") from exc
    except ET.ParseError as exc:
        raise GrobidError("GROBID returned invalid TEI XML") from exc

    def text_for(xpath: str) -> str:
        node = root.find(xpath, {"tei": "http://www.tei-c.org/ns/1.0"})
        if node is None:
            return ""
        return " ".join(" ".join(node.itertext()).split())

    title = text_for(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title")
    abstract = text_for(".//tei:teiHeader/tei:profileDesc/tei:abstract")
    body = text_for(".//tei:text/tei:body")
    bibliography = []
    for ref in root.findall(".//tei:listBibl/tei:biblStruct", {"tei": "http://www.tei-c.org/ns/1.0"}):
        ref_text = " ".join(" ".join(ref.itertext()).split())
        if ref_text:
            bibliography.append(ref_text[:1_500])
    chunks = []
    if title:
        chunks.extend([f"# {title}", ""])
    if abstract:
        chunks.extend(["## Abstract", abstract, ""])
    if body:
        chunks.extend(["## Full text", body, ""])
    if bibliography:
        chunks.extend(["## Extracted references (verify against the PDF)", *[f"- {item}" for item in bibliography[:300]]])
    if not any((title, abstract, body, bibliography)):
        raise GrobidError("GROBID produced no readable article content")
    return "\n".join(chunks)


def _extract_optional(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("PDF input requires the optional dependency: pip install 'argumentum[pdf]'") from exc
        reader = PdfReader(str(path))
        chunks: list[str] = []
        total_chars = 0
        truncated = False
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES or total_chars >= MAX_EXTRACTED_TEXT_CHARS:
                truncated = True
                break
            text = page.extract_text() or ""
            remaining = MAX_EXTRACTED_TEXT_CHARS - total_chars
            chunks.append(text[:remaining])
            total_chars += min(len(text), remaining)
            if len(text) > remaining:
                truncated = True
                break
        if len(reader.pages) > MAX_PDF_PAGES:
            truncated = True
        if truncated:
            chunks.append("[PDF extraction truncated by configured page/text limits.]")
        return "\n\n".join(chunks)
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("DOCX input requires the optional dependency: pip install 'argumentum[docx]'") from exc
        doc = Document(str(path))
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)
    raise ValueError(f"Unsupported document type: {path.suffix}")


def read_materials(directory: str | Path | None, grobid_url: str | None = None, grobid_timeout_seconds: int = 180) -> tuple[list[InputDocument], list[str]]:
    """Read supported files deterministically, with size limits and SHA-256 provenance."""
    if directory is None:
        return [], []
    root = Path(directory).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Input directory does not exist or is not a directory: {root}")

    paths = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    documents: list[InputDocument] = []
    warnings: list[str] = []
    total = 0
    for path in paths:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_TEXT | OPTIONAL_DOCUMENTS:
            continue
        if len(documents) >= MAX_FILES:
            warnings.append(f"Input limit reached ({MAX_FILES} files); remaining files were skipped.")
            break
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            warnings.append(f"Skipped {path.name}: file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MiB.")
            continue
        if total + size > MAX_TOTAL_BYTES:
            warnings.append("Total input limit reached (100 MiB); remaining files were skipped.")
            break
        try:
            if suffix == ".pdf" and grobid_url:
                try:
                    text = _extract_grobid(path, grobid_url, grobid_timeout_seconds)
                except (GrobidError, OSError) as grobid_exc:
                    warnings.append(f"GROBID extraction failed for {path.name} ({type(grobid_exc).__name__}); using local PDF text extraction.")
                    text = _extract_optional(path)
            else:
                text = _extract_optional(path) if suffix in OPTIONAL_DOCUMENTS else path.read_text(encoding="utf-8")
        except Exception as exc:
            # Malformed or parser-hostile individual documents must not abort an
            # otherwise valid research run. Record only the error type.
            warnings.append(f"Could not read {path.name}: {type(exc).__name__}.")
            continue
        if not text.strip():
            warnings.append(f"Skipped {path.name}: no extractable text was found.")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(text) > MAX_EXTRACTED_TEXT_CHARS:
            text = text[: MAX_EXTRACTED_TEXT_CHARS - 45] + "\n[Document text truncated by configured limit.]"
        documents.append(InputDocument(path=str(path.relative_to(root)), text=text, sha256=digest, size_bytes=size))
        total += size
    return documents, warnings


def summarize_csv_documents(documents: Iterable[InputDocument]) -> list[dict[str, object]]:
    """Return bounded previews only; never perform inference or statistical analysis."""
    summaries: list[dict[str, object]] = []
    for document in documents:
        if not document.path.lower().endswith(".csv"):
            continue
        if len(summaries) >= MAX_CSV_PREVIEW_FILES:
            break
        try:
            reader = csv.DictReader(document.text.splitlines())
            rows = list(islice(reader, MAX_CSV_SCAN_ROWS + 1))
        except csv.Error:
            continue

        scan_truncated = len(rows) > MAX_CSV_SCAN_ROWS
        rows = rows[:MAX_CSV_SCAN_ROWS]
        columns = (reader.fieldnames or [])[:MAX_CSV_COLUMNS]
        preview: list[dict[str, str]] = []
        for row in rows[:MAX_CSV_PREVIEW_ROWS]:
            safe_row: dict[str, str] = {}
            for key, value in row.items():
                safe_key = str(key)[:120] if key is not None else "_extra"
                safe_row[safe_key] = str(value)[:MAX_CSV_CELL_CHARS] if value is not None else ""
            preview.append(safe_row)

        source_excerpt_complete = len(document.text.encode("utf-8")) >= document.size_bytes
        summaries.append({
            "path": document.path,
            "row_count_in_excerpt": len(rows),
            "row_count_is_complete": source_excerpt_complete and not scan_truncated,
            "columns": [str(column)[:120] for column in columns],
            "preview": preview,
            "note": (
                f"Bounded excerpt only; scanned at most {MAX_CSV_SCAN_ROWS} rows and previewed the first "
                f"{MAX_CSV_PREVIEW_ROWS}. no statistical analysis was run. The excerpt may not contain the full table."
            ),
        })
    return summaries
