"""Data passed between the pipeline and the API."""

from dataclasses import dataclass


@dataclass
class DocumentInfo:
    doc_id: str
    name: str
    chunks: int


@dataclass
class RetrievedChunk:
    number: int  # 1-based, used for [n] citations
    source: str
    page: int | None
    score: float  # cosine similarity -1..1, higher is better
    text: str
