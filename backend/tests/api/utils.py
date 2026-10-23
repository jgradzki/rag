"""Helpers for the API tests: an app with fake LLM and embeddings, upload, SSE parsing."""

import json

from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import FakeListChatModel

from app.config import Settings
from app.main import create_app
from app.rag.service import RagService

FAKE_ANSWER = "Curiosity landed in Gale Crater [1]."


def make_client(
    tmp_path, min_relevance: float, max_upload_mb: float = 10, max_upload_files: int = 20, llm=None
) -> TestClient:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        index_samples_on_startup=False,
        max_upload_mb=max_upload_mb,
        max_upload_files=max_upload_files,
    )
    service = RagService(
        llm=llm or FakeListChatModel(responses=[FAKE_ANSWER]),
        embeddings=DeterministicFakeEmbedding(size=64),
        persist_dir=tmp_path / "chroma",
        chunk_size=200,
        chunk_overlap=20,
        min_relevance=min_relevance,
    )
    return TestClient(create_app(settings, service))


def parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def upload(client, name: str, content: str | bytes):
    data = content.encode() if isinstance(content, str) else content
    return client.post("/api/documents", files=[("files", (name, data))])
