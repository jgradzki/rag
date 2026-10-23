import pytest

from app.api.routes.documents import safe_file_name
from tests.api.utils import make_client, upload


def test_upload_list_delete(client):
    res = upload(client, "mars.md", "Curiosity landed in Gale Crater. " * 20)
    assert res.status_code == 200
    [doc] = res.json()
    assert doc["name"] == "mars.md" and doc["chunks"] > 1

    assert client.get("/api/documents").json() == [doc]

    assert client.delete(f"/api/documents/{doc['doc_id']}").status_code == 200
    assert client.get("/api/documents").json() == []
    assert client.delete(f"/api/documents/{doc['doc_id']}").status_code == 404


def test_reupload_replaces_instead_of_duplicating(client):
    assert upload(client, "a.txt", "same content " * 30).status_code == 200
    assert upload(client, "b.txt", "same content " * 30).status_code == 200
    [doc] = client.get("/api/documents").json()
    assert doc["name"] == "b.txt"  # same content = same document, latest name wins


def test_duplicate_content_in_one_request_is_one_document(client):
    files = [("files", ("a.txt", b"Same text " * 20)), ("files", ("copy.txt", b"Same text " * 20))]
    res = client.post("/api/documents", files=files)
    assert res.status_code == 200
    assert res.json() == client.get("/api/documents").json()  # response matches the index
    assert [d["name"] for d in res.json()] == ["copy.txt"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../evil.md", "evil.md"),
        ("..\\..\\evil.md", "evil.md"),
        ("C:/Windows/evil.md", "evil.md"),
        ("bad\nname\x00.md", "badname.md"),
        ("", "upload"),
        (None, "upload"),
    ],
)
def test_safe_file_name(raw, expected):
    assert safe_file_name(raw) == expected


def test_rejects_unsupported_file(client):
    res = upload(client, "photo.jpg", "not really a jpg")
    assert res.status_code == 400


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("broken.pdf", b"not a pdf"),  # pypdf error used to surface as a 500
        ("latin2.txt", b"\xff\xfe\xb1"),  # not UTF-8
        ("empty.txt", b""),  # used to "succeed" with 0 chunks and never show up
        ("blank.md", b"  \n\n  "),
    ],
)
def test_rejects_unreadable_files(client, name, content):
    res = upload(client, name, content)
    assert res.status_code == 400
    assert res.json()["detail"].startswith(f"Could not read {name}")
    assert client.get("/api/documents").json() == []


@pytest.mark.parametrize(("extra_bytes", "status"), [(0, 200), (1, 413)])
def test_size_limit_boundary(tmp_path, extra_bytes, status):
    max_bytes = int(0.001 * 1024 * 1024)  # 1048
    with make_client(tmp_path, min_relevance=-1.0, max_upload_mb=0.001) as client:
        content = ("word " * 300)[: max_bytes + extra_bytes]
        res = upload(client, "file.txt", content)
        assert res.status_code == status
        assert len(client.get("/api/documents").json()) == (1 if status == 200 else 0)


@pytest.mark.parametrize(("count", "status"), [(2, 200), (3, 413)])
def test_file_count_limit(tmp_path, count, status):
    with make_client(tmp_path, min_relevance=-1.0, max_upload_files=2) as client:
        files = [("files", (f"f{i}.txt", f"File number {i}".encode())) for i in range(count)]
        res = client.post("/api/documents", files=files)
        assert res.status_code == status
        assert len(client.get("/api/documents").json()) == (count if status == 200 else 0)


@pytest.mark.parametrize("bad_file", [("photo.jpg", b"jpg"), ("broken.pdf", b"not a pdf")])
def test_multi_file_upload_is_all_or_nothing(client, bad_file):
    files = [("files", ("good.txt", b"Valid text " * 20)), ("files", bad_file)]
    res = client.post("/api/documents", files=files)
    assert res.status_code == 400
    assert client.get("/api/documents").json() == []  # good.txt was not stored either
