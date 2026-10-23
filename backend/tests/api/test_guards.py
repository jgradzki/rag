import pytest

from app.api.guards import MAX_JSON_BODY, MULTIPART_OVERHEAD, RequestGuard
from app.config import Settings
from tests.api.utils import make_client, upload


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        (None, 200),  # curl, scripts: no Origin header
        ("http://localhost:5173", 200),  # the dev frontend
        ("http://localhost:8080", 200),  # the Docker frontend
        ("http://evil.example", 403),  # another website's page
        ("null", 403),  # sandboxed iframe, file:// page
    ],
)
def test_writes_only_from_allowed_origins(client, origin, status):
    headers = {"Origin": origin} if origin else {}
    files = [("files", ("a.txt", b"Some text " * 20))]
    res = client.post("/api/documents", files=files, headers=headers)
    assert res.status_code == status
    assert len(client.get("/api/documents").json()) == (1 if status == 200 else 0)

    chat = client.post("/api/chat", json={"question": "Hi?"}, headers=headers)
    assert chat.status_code == status
    if status == 403:
        assert client.delete("/api/documents/whatever", headers=headers).status_code == 403


def test_foreign_origin_is_rejected_before_the_body_is_read(client):
    # Invalid JSON would get 422 from FastAPI - a 403 shows the guard answered first.
    res = client.post(
        "/api/chat",
        content=b"{not json",
        headers={"Origin": "http://evil.example", "Content-Type": "application/json"},
    )
    assert res.status_code == 403


def test_upload_body_over_the_limit_is_rejected_up_front(tmp_path):
    # 1 file x (1048 bytes + multipart allowance) - this body is too big for any upload.
    with make_client(tmp_path, min_relevance=-1.0, max_upload_mb=0.001, max_upload_files=1) as c:
        res = upload(c, "big.txt", "x" * 20_000)
    assert res.status_code == 413
    assert res.json()["detail"] == "Upload too large (at most 1 files of 0.001 MB each)"


def test_a_max_size_file_fits_the_upload_allowance(tmp_path):
    # The guard's per-file allowance must cover the multipart headers of a file that is
    # exactly MAX_UPLOAD_MB - the route then accepts it.
    with make_client(tmp_path, min_relevance=-1.0, max_upload_mb=0.001, max_upload_files=1) as c:
        res = upload(c, "max.txt", ("word " * 300)[:1048])
    assert res.status_code == 200


def guard_check(path: str, length: int, method: str = "POST"):
    settings = Settings(_env_file=None, max_upload_mb=0.001, max_upload_files=2)
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"content-length", str(length).encode())],
    }
    return RequestGuard(app=None, settings=settings).check(scope)


@pytest.mark.parametrize("path", ["/api/documents", "/api/documents/"])
def test_upload_limit_boundary(path):
    limit = 2 * (1048 + MULTIPART_OVERHEAD)
    assert guard_check(path, limit) is None
    assert guard_check(path, limit + 1)[0] == 413


def test_json_body_limit_boundary():
    assert guard_check("/api/chat", MAX_JSON_BODY) is None
    assert guard_check("/api/chat", MAX_JSON_BODY + 1)[0] == 413


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/api/documents", "multipart/form-data; boundary=x"),
        ("/api/chat", "application/json"),
    ],
)
def test_chunked_bodies_are_rejected(client, path, content_type):
    # An iterator is sent chunked, with no Content-Length: its size is unknown until it
    # has been read whole, so the 64 KB / upload limits could not be enforced.
    res = client.post(
        path, content=iter([b'{"question": "x"}']), headers={"Content-Type": content_type}
    )
    assert res.status_code == 411


def test_guard_answers_carry_cors_headers(client):
    # An allowed origin must be able to read why its request was refused.
    origin = "http://localhost:5173"
    res = client.post("/api/chat", json={"question": "x" * 70_000}, headers={"Origin": origin})
    assert res.status_code == 413
    assert res.headers["access-control-allow-origin"] == origin


def test_wildcard_origin_is_rejected_at_startup():
    with pytest.raises(ValueError, match="list each allowed origin"):
        Settings(_env_file=None, cors_origins=["*"])
