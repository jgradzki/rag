"""Loading files and splitting them into chunks ready for embedding."""

import hashlib
import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pypdf.errors import DependencyError, FileNotDecryptedError, PyPdfError

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

logger = logging.getLogger(__name__)


class UnsupportedFileError(ValueError):
    pass


class UnreadableFileError(ValueError):
    """The file has a supported type but no text could be read from it."""


def file_id(path: Path) -> str:
    """Stable id derived from file content - re-uploading the same file replaces it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_file(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        # One Document per page, so answers can point to the page number.
        try:
            reader = PdfReader(path)
            return [
                Document(page_content=page.extract_text() or "", metadata={"page": i})
                for i, page in enumerate(reader.pages)
            ]
        # A PDF locked with a password, or encrypted with AES (which pypdf can only read
        # with the extra `cryptography` package - not installed, to keep the image small).
        except (FileNotDecryptedError, DependencyError) as e:
            raise UnreadableFileError(
                "encrypted PDFs are not supported - upload an unencrypted copy"
            ) from e
        except PyPdfError as e:
            raise UnreadableFileError(f"not a valid PDF ({e})") from e
        except Exception as e:  # damaged files also raise KeyError, ValueError, ...
            logger.warning("PDF parsing failed for %s", path.name, exc_info=True)
            raise UnreadableFileError(f"not a readable PDF ({type(e).__name__}: {e})") from e
    if suffix in {".txt", ".md"}:
        return [Document(page_content=decode_text(path.read_bytes()))]
    raise UnsupportedFileError(
        f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def decode_text(data: bytes) -> str:
    """UTF-8 (a leading BOM dropped), or UTF-16 when a BOM says so - as Windows Notepad's
    "Unicode" and PowerShell 5's `>` write it. Anything else is not guessed."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding, name = "utf-16", "UTF-16"
    else:
        encoding, name = "utf-8-sig", "UTF-8"
    try:
        return data.decode(encoding)
    except UnicodeDecodeError as e:
        raise UnreadableFileError(f"not valid {name} text - save the file as UTF-8") from e


def split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_documents(docs)


def prepare_chunks(
    path: Path, display_name: str, chunk_size: int, chunk_overlap: int
) -> tuple[str, list[Document]]:
    """Load a file, split it and tag every chunk with document-level metadata."""
    doc_id = file_id(path)
    chunks = split_documents(load_file(path), chunk_size, chunk_overlap)
    if not chunks:
        raise UnreadableFileError(
            "no text could be extracted (an empty file or a scanned PDF without a text layer)"
        )
    for i, chunk in enumerate(chunks):
        page = chunk.metadata.get("page")
        # Chroma accepts only flat str/int/float/bool metadata values.
        chunk.metadata = {
            "doc_id": doc_id,
            "source": display_name,
            "chunk": i,
            **({"page": int(page) + 1} if page is not None else {}),  # 1-based for humans
        }
    return doc_id, chunks
