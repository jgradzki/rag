"""Local text embeddings with fastembed (ONNX, runs on CPU - no API key needed)."""

from pathlib import Path

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings


class FastEmbedEmbeddings(Embeddings):
    """Adapter exposing a fastembed model through LangChain's `Embeddings` interface.

    LangChain components (like the Chroma vector store) only need two methods:
    one for embedding many documents and one for embedding a single query.
    """

    def __init__(self, model_name: str, cache_dir: Path | None = None):
        # Downloads the model on first use (~220 MB for the default one).
        self.model = TextEmbedding(
            model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
