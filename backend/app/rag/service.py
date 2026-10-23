"""RagService: indexing documents, retrieving relevant chunks, generating answers."""

from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.vectorstores.utils import maximal_marginal_relevance

from app.rag.citations import drop_invalid_citations
from app.rag.ingest import prepare_chunks
from app.rag.models import DocumentInfo, RetrievedChunk
from app.rag.prompts import NO_DOCUMENTS_ANSWER, PROMPT, format_context

# Chroma rejects a single insert above its max batch size (~5400 on SQLite),
# so large documents are added in smaller batches.
ADD_BATCH_SIZE = 1000


class RagService:
    # The app passes every value from Settings (main.build_service); these defaults are
    # conveniences for tests and are not the app's defaults.
    def __init__(
        self,
        llm: BaseChatModel,
        embeddings: Embeddings,
        persist_dir: Path,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        top_k: int = 4,
        min_relevance: float = 0.0,
        fetch_k: int = 20,
        mmr_lambda: float = 1.0,
    ):
        self.vectorstore = Chroma(
            collection_name="documents",
            embedding_function=embeddings,
            persist_directory=str(persist_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )
        self.embeddings = embeddings
        self.chain = PROMPT | llm | StrOutputParser()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.min_relevance = min_relevance
        self.fetch_k = fetch_k
        self.mmr_lambda = mmr_lambda

    # --- Indexing -------------------------------------------------------------

    def prepare_file(self, path: Path, display_name: str) -> tuple[str, list[Document]]:
        """Parse and chunk a file without storing it (raises on unreadable files)."""
        return prepare_chunks(path, display_name, self.chunk_size, self.chunk_overlap)

    def add_chunks(self, doc_id: str, display_name: str, chunks: list[Document]) -> DocumentInfo:
        self.delete_document(doc_id)  # re-indexing the same file replaces old chunks
        try:
            for start in range(0, len(chunks), ADD_BATCH_SIZE):
                batch = chunks[start : start + ADD_BATCH_SIZE]
                ids = [f"{doc_id}-{c.metadata['chunk']}" for c in batch]
                self.vectorstore.add_documents(batch, ids=ids)
        except Exception:
            # Don't leave a half-indexed document that the list would show as complete.
            self.delete_document(doc_id)
            raise
        return DocumentInfo(doc_id=doc_id, name=display_name, chunks=len(chunks))

    def add_file(self, path: Path, display_name: str) -> DocumentInfo:
        doc_id, chunks = self.prepare_file(path, display_name)
        return self.add_chunks(doc_id, display_name, chunks)

    def list_documents(self) -> list[DocumentInfo]:
        docs: dict[str, DocumentInfo] = {}
        for meta in self.vectorstore.get(include=["metadatas"])["metadatas"]:
            info = docs.setdefault(meta["doc_id"], DocumentInfo(meta["doc_id"], meta["source"], 0))
            info.chunks += 1
        return sorted(docs.values(), key=lambda d: d.name.lower())

    def delete_document(self, doc_id: str) -> bool:
        ids = self.vectorstore.get(where={"doc_id": doc_id}, include=[])["ids"]
        if ids:
            self.vectorstore.delete(ids=ids)
        return bool(ids)

    def is_empty(self) -> bool:
        return not self.vectorstore.get(limit=1, include=[])["ids"]

    # --- Retrieval & generation ----------------------------------------------

    def retrieve(self, question: str) -> list[RetrievedChunk]:
        k = max(self.fetch_k, self.top_k) if self.mmr_lambda < 1.0 else self.top_k
        query = self.embeddings.embed_query(question)  # once - MMR below needs it too
        # Chroma returns cosine distance (0..2) despite the method name; relevance is
        # 1 - distance (-1..1).
        results = self.vectorstore.similarity_search_by_vector_with_relevance_scores(query, k=k)
        # The vector store always returns k results, even when none of them is
        # related to the question - drop the weak ones so they don't mislead the LLM.
        relevant = [(doc, 1.0 - dist) for doc, dist in results if 1.0 - dist >= self.min_relevance]
        selected = sorted(self._diversify(query, relevant), key=lambda r: r[1], reverse=True)
        return [_to_retrieved(i, doc, score) for i, (doc, score) in enumerate(selected, 1)]

    def _diversify(
        self, query: list[float], candidates: list[tuple[Document, float]]
    ) -> list[tuple[Document, float]]:
        """Pick top_k candidates with Maximal Marginal Relevance.

        Each pick scores relevance to the question minus similarity to the chunks already
        picked (weighted by mmr_lambda; 1.0 = relevance only). This keeps near-duplicate
        chunks from filling every slot when a corpus repeats itself. It does not rescue
        the second topic of a two-topic question: in a single query vector that topic
        scores at noise level (measured on the sample docs, see config.py).
        """
        if self.mmr_lambda >= 1.0 or len(candidates) <= self.top_k:
            return candidates[: self.top_k]
        stored = self.vectorstore.get(ids=[doc.id for doc, _ in candidates], include=["embeddings"])
        by_id = dict(zip(stored["ids"], stored["embeddings"], strict=True))  # get() reorders
        picked = maximal_marginal_relevance(
            np.array(query),
            [by_id[doc.id] for doc, _ in candidates],
            lambda_mult=self.mmr_lambda,
            k=self.top_k,
        )
        return [candidates[i] for i in picked]

    async def stream_answer(
        self, question: str, chunks: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        if not chunks and self.is_empty():
            yield NO_DOCUMENTS_ANSWER
            return
        # With no relevant chunks the LLM still runs, so it can say "not found"
        # in the user's language.
        tokens = self.chain.astream({"question": question, "context": format_context(chunks)})
        async for text in drop_invalid_citations(tokens, len(chunks)):
            yield text


def _to_retrieved(number: int, doc: Document, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        number=number,
        source=doc.metadata.get("source", "unknown"),
        page=doc.metadata.get("page"),
        score=round(score, 3),
        text=doc.page_content,
    )
