import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import FakeListChatModel

from app.rag.service import RagService


@pytest.fixture
def service(tmp_path):
    return RagService(
        llm=FakeListChatModel(responses=["-"]),
        embeddings=DeterministicFakeEmbedding(size=64),
        persist_dir=tmp_path / "chroma",
        chunk_size=200,
        chunk_overlap=20,
    )


def test_reindexing_with_fewer_chunks_leaves_no_stale_ones(service, tmp_path):
    # Chunk ids are "<doc_id>-<n>": re-adding fewer chunks only overwrites the first ones,
    # so the old chunks must be deleted first (e.g. after CHUNK_SIZE was raised).
    path = tmp_path / "a.txt"
    path.write_text("Sentence here. " * 60, encoding="utf-8")
    doc_id, chunks = service.prepare_file(path, "a.txt")
    assert len(chunks) > 2
    service.add_chunks(doc_id, "a.txt", chunks)
    service.add_chunks(doc_id, "a.txt", chunks[:2])
    assert [d.chunks for d in service.list_documents()] == [2]
    assert len(service.vectorstore.get()["ids"]) == 2


def test_large_documents_are_added_in_batches(service, tmp_path, monkeypatch):
    calls = []
    store = service.vectorstore
    original = store.add_documents
    monkeypatch.setattr("app.rag.service.ADD_BATCH_SIZE", 3)
    monkeypatch.setattr(
        store, "add_documents", lambda docs, **kw: calls.append(len(docs)) or original(docs, **kw)
    )
    path = tmp_path / "long.md"
    path.write_text("Paragraph of text. " * 200, encoding="utf-8")

    doc = service.add_file(path, "long.md")

    assert doc.chunks > 3
    assert max(calls) <= 3 and sum(calls) == doc.chunks
    assert service.list_documents() == [doc]


class TopicEmbeddings(Embeddings):
    """Predictable vectors: one axis per topic word, plus a small per-text tweak."""

    def embed_query(self, text: str) -> list[float]:
        return [text.count("mars"), text.count("rag"), len(text) % 7 / 100]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


@pytest.mark.parametrize(
    ("mmr_lambda", "expected_topics"),
    [
        (1.0, ["mars", "mars"]),  # relevance only: two near-duplicates
        (0.5, ["mars", "rag"]),  # MMR: the second topic gets a slot
    ],
)
def test_mmr_trades_near_duplicates_for_another_topic(tmp_path, mmr_lambda, expected_topics):
    service = RagService(
        llm=FakeListChatModel(responses=["-"]),
        embeddings=TopicEmbeddings(),
        persist_dir=tmp_path,
        top_k=2,
        mmr_lambda=mmr_lambda,
    )
    # The rag chunk is stored first, so Chroma's get() order differs from the relevance
    # order - feeding its embeddings to MMR without mapping them by id would fail here.
    for name, text in [
        ("d.md", "rag hybrid search"),
        ("a.md", "mars dust"),
        ("b.md", "mars storms"),
        ("c.md", "mars panels!"),
    ]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        service.add_file(tmp_path / name, name)

    chunks = service.retrieve("mars mars rag")

    # Which of the near-identical mars chunks wins is incidental - the topics are not.
    assert [c.text.split()[0] for c in chunks] == expected_topics
    assert [c.number for c in chunks] == [1, 2]
    assert chunks[0].score >= chunks[1].score  # still ordered by relevance


class FailingEmbeddings(TopicEmbeddings):
    """Embeds the first batch, then fails - like a crash halfway through a big file."""

    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("out of memory")
        return super().embed_documents(texts)


def test_failed_indexing_leaves_no_partial_document(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.service.ADD_BATCH_SIZE", 1)
    service = RagService(
        llm=FakeListChatModel(responses=["-"]),
        embeddings=FailingEmbeddings(),
        persist_dir=tmp_path,
    )
    chunks = [
        Document(text, metadata={"doc_id": "d1", "source": "a.md", "chunk": i})
        for i, text in enumerate(["mars dust", "mars storms"])
    ]

    with pytest.raises(RuntimeError):
        service.add_chunks("d1", "a.md", chunks)

    assert service.list_documents() == []
