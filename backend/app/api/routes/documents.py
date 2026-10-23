import tempfile
import unicodedata
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import RagDep, SettingsDep
from app.api.schemas import Deleted
from app.rag.ingest import SUPPORTED_EXTENSIONS, UnreadableFileError, UnsupportedFileError
from app.rag.models import DocumentInfo

router = APIRouter(prefix="/api/documents", tags=["documents"])


def safe_file_name(filename: str | None) -> str:
    """The bare file name (no directories from either OS), without control characters."""
    name = PureWindowsPath(filename or "").name  # splits on both / and \
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    return name or "upload"


def save_upload(upload: UploadFile, path: Path, max_bytes: int) -> bool:
    """Stream an upload to disk; False (and stop) as soon as it exceeds max_bytes."""
    written = 0
    with path.open("wb") as f:
        while block := upload.file.read(1024 * 1024):
            written += len(block)
            if written > max_bytes:
                return False
            f.write(block)
    return True


@router.get("")
def list_documents(rag: RagDep) -> list[DocumentInfo]:
    return rag.list_documents()


@router.post("")
def upload_documents(
    files: list[UploadFile], rag: RagDep, settings: SettingsDep
) -> list[DocumentInfo]:
    # All-or-nothing for bad input: every file is validated and parsed before any is
    # stored, so one bad file in a multi-file upload doesn't leave the others indexed.
    if len(files) > settings.max_upload_files:
        raise HTTPException(
            413, f"Too many files: {len(files)} (at most {settings.max_upload_files})"
        )
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    too_large = f"is larger than {settings.max_upload_mb:g} MB"
    names = [safe_file_name(upload.filename) for upload in files]
    for upload, name in zip(files, names, strict=True):
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type: {name}")
        if upload.size is not None and upload.size > max_bytes:
            raise HTTPException(413, f"{name} {too_large}")

    # doc_id is a content hash: the same content twice in one request is one document.
    prepared: dict[str, tuple[str, list]] = {}
    # The original files aren't needed after parsing - chunks live in Chroma.
    with tempfile.TemporaryDirectory() as tmp:
        for i, (upload, name) in enumerate(zip(files, names, strict=True)):
            path = Path(tmp) / f"upload{i}{Path(name).suffix.lower()}"
            if not save_upload(upload, path, max_bytes):
                raise HTTPException(413, f"{name} {too_large}")
            try:
                doc_id, chunks = rag.prepare_file(path, name)
            except (UnsupportedFileError, UnreadableFileError) as e:
                raise HTTPException(400, f"Could not read {name}: {e}") from e
            prepared[doc_id] = (name, chunks)

    return [rag.add_chunks(doc_id, name, chunks) for doc_id, (name, chunks) in prepared.items()]


@router.delete("/{doc_id}")
def delete_document(doc_id: str, rag: RagDep) -> Deleted:
    if not rag.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    return Deleted(deleted=doc_id)
