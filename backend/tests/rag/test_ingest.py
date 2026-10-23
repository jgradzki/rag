import io

import pytest
from pypdf import PdfWriter
from pypdf.errors import DependencyError

from app.rag.ingest import UnreadableFileError, UnsupportedFileError, file_id, prepare_chunks


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page ("" = no text layer)."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))}]"
        f" /Count {len(pages)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            f" /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")

    pdf, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return pdf


def test_pdf_chunks_carry_one_based_page_numbers(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(make_pdf(["Text on the first page.", "Text on the second page."]))

    _, chunks = prepare_chunks(path, "report.pdf", chunk_size=1000, chunk_overlap=0)

    assert [(c.metadata["page"], c.page_content) for c in chunks] == [
        (1, "Text on the first page."),
        (2, "Text on the second page."),
    ]


def test_pdf_without_text_layer_is_rejected(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_pdf(["", ""]))  # like a scanned PDF: pages, but no text
    with pytest.raises(UnreadableFileError, match="no text could be extracted"):
        prepare_chunks(path, "scan.pdf", 1000, 150)


def test_prepare_chunks_splits_and_tags_metadata(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(10)), "utf-8")

    doc_id, chunks = prepare_chunks(path, "notes.md", chunk_size=300, chunk_overlap=50)

    assert doc_id == file_id(path)
    assert len(chunks) > 1
    assert all(len(c.page_content) <= 300 for c in chunks)
    assert [c.metadata["chunk"] for c in chunks] == list(range(len(chunks)))
    assert all(c.metadata["source"] == "notes.md" for c in chunks)
    assert all("page" not in c.metadata for c in chunks)


def test_same_content_gives_same_id(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("identical", "utf-8")
    b.write_text("identical", "utf-8")
    assert file_id(a) == file_id(b)


def test_unsupported_extension(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(UnsupportedFileError):
        prepare_chunks(path, "image.png", 1000, 150)


def test_password_protected_pdf_is_rejected(tmp_path):
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf(["Secret"])))
    writer.encrypt(user_password="secret", algorithm="RC4-128")  # AES needs `cryptography`
    path = tmp_path / "locked.pdf"
    writer.write(path)

    with pytest.raises(UnreadableFileError, match="encrypted PDFs are not supported"):
        prepare_chunks(path, "locked.pdf", chunk_size=200, chunk_overlap=0)


def test_aes_encrypted_pdf_is_rejected(tmp_path, monkeypatch):
    def aes_reader(path):
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr("app.rag.ingest.PdfReader", aes_reader)
    path = tmp_path / "aes.pdf"
    path.write_bytes(make_pdf(["Secret"]))

    with pytest.raises(UnreadableFileError, match="encrypted PDFs are not supported"):
        prepare_chunks(path, "aes.pdf", chunk_size=200, chunk_overlap=0)


@pytest.mark.parametrize(
    "data",
    [
        "﻿Zażółć gęślą jaźń".encode(),  # UTF-8 with a BOM
        "Zażółć gęślą jaźń".encode("utf-16"),  # UTF-16 with a BOM (Notepad "Unicode")
    ],
)
def test_text_encodings_with_a_bom(tmp_path, data):
    path = tmp_path / "note.txt"
    path.write_bytes(data)
    doc_id, chunks = prepare_chunks(path, "note.txt", chunk_size=200, chunk_overlap=0)
    assert chunks[0].page_content == "Zażółć gęślą jaźń"  # no BOM left in the text


def test_text_in_another_encoding_is_rejected(tmp_path):
    path = tmp_path / "latin2.txt"
    path.write_bytes("Zażółć".encode("iso-8859-2"))
    with pytest.raises(UnreadableFileError, match="save the file as UTF-8"):
        prepare_chunks(path, "latin2.txt", chunk_size=200, chunk_overlap=0)
