from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import FakeListChatModel

from app.config import Settings
from app.main import build_service, create_app
from app.rag.service import RagService
from tests.api.utils import FAKE_ANSWER


def test_samples_are_indexed_only_on_the_first_start(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "sample.md").write_text("Sample text about Mars.", encoding="utf-8")
    settings = Settings(
        _env_file=None, data_dir=tmp_path, sample_docs_dir=samples, index_samples_on_startup=True
    )
    service = RagService(
        llm=FakeListChatModel(responses=[FAKE_ANSWER]),
        embeddings=DeterministicFakeEmbedding(size=64),
        persist_dir=settings.chroma_dir,
    )

    with TestClient(create_app(settings, service)) as client:
        [doc] = client.get("/api/documents").json()
        client.delete(f"/api/documents/{doc['doc_id']}")
    with TestClient(create_app(settings, service)) as client:  # restart
        assert client.get("/api/documents").json() == []


def test_build_service_passes_every_setting_on(tmp_path, monkeypatch):
    built = {}

    class FakeEmbeddings(DeterministicFakeEmbedding):
        def __init__(self, model_name, cache_dir):  # the real one would download a model
            super().__init__(size=8)
            built.update(model_name=model_name, cache_dir=cache_dir)

    monkeypatch.setattr("app.main.FastEmbedEmbeddings", FakeEmbeddings)
    monkeypatch.setattr("app.main.create_llm", lambda s: FakeListChatModel(responses=["-"]))
    # Every value differs from the RagService defaults, so a dropped mapping shows up.
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_model="some/model",
        chunk_size=321,
        chunk_overlap=12,
        top_k=3,
        min_relevance=0.33,
        fetch_k=7,
        mmr_lambda=0.4,
    )

    service = build_service(settings)

    assert built == {"model_name": "some/model", "cache_dir": tmp_path / "models"}
    assert (service.chunk_size, service.chunk_overlap) == (321, 12)
    assert (service.top_k, service.fetch_k) == (3, 7)
    assert (service.min_relevance, service.mmr_lambda) == (0.33, 0.4)
    assert (tmp_path / "chroma" / "chroma.sqlite3").exists()  # the index went to data_dir
