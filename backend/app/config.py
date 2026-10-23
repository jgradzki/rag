"""Application settings loaded from environment variables / `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # --- LLM provider -------------------------------------------------------
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"

    # Read from backend/.env too: pydantic-settings does not export .env values to the
    # process environment, where the Anthropic SDK would otherwise look for the key.
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    # How much the model "thinks" before answering.
    # Answers in RAG come from the retrieved context, so "low" is fast and cheap.
    # Empty = not sent, for a model without the effort parameter.
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = "low"
    # Lower it for a model with a smaller output limit.
    anthropic_max_tokens: int = Field(16000, gt=0)

    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"
    # Thinking mode of reasoning models (qwen3, deepseek-r1...). None (unset) = the model's
    # default, which works for every model; true is rejected by models without a thinking
    # mode (e.g. llama3.2). Measured with qwen3:8b on the sample docs: false halves the time
    # to first token (2.4 s vs 5.0 s median), but the model then answered an off-topic
    # question from its own knowledge instead of saying it is not in the docs.
    ollama_reasoning: bool | None = None

    # --- Embeddings (computed locally, independent of the LLM provider) -----
    # Multilingual model, so Polish and English documents both work.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # --- Chunking & retrieval -----------------------------------------------
    # The embedding model reads at most 128 tokens; longer chunks are silently truncated.
    # 450 characters stays within the limit (max ~112 tokens on the sample docs and Polish
    # text). top_k 8 keeps about the same context volume as 4 x 1000 characters did; on 10
    # sample questions it retrieved every answer chunk (4 x 1000: 9/10, 6 x 450: 8/10).
    chunk_size: int = 450
    chunk_overlap: int = 70
    top_k: int = 8
    # Chunks with cosine relevance below this are not passed to the LLM. Relevance is cosine
    # similarity: -1..1, in practice ~0.2 for unrelated text and up to ~0.8 for a close match.
    # Measured on the sample docs: answer chunks scored >= 0.239 (cross-lingual questions
    # score lowest), off-topic questions <= 0.22. Depends on the embedding model and chunk size.
    min_relevance: float = 0.2
    # Maximal Marginal Relevance: from the fetch_k best chunks pick top_k that are relevant
    # but not near-duplicates. mmr_lambda 1.0 = relevance only (off), lower = more diversity.
    # Off by default: on the sample docs 0.6-0.85 lost answer chunks and did not fix
    # two-topic questions (the second topic scores at noise level in a single query vector).
    # It helps when a corpus holds many near-duplicate chunks.
    fetch_k: int = 20
    mmr_lambda: float = 1.0

    # --- Storage ------------------------------------------------------------
    data_dir: Path = BACKEND_DIR / "data"
    # Where the embedding model is downloaded; defaults to <data_dir>/models. Set it to
    # share one download between instances with different data dirs (e.g. test runs).
    models_dir: Path | None = None
    sample_docs_dir: Path = BACKEND_DIR / "sample_docs"
    index_samples_on_startup: bool = True

    # Per-file upload limit. Indexing is CPU-bound: a 10 MB text file takes minutes.
    max_upload_mb: float = 10
    # Files per upload request - bounds the indexing work one request can start.
    max_upload_files: int = 20

    # Browser origins allowed to call the API: the Vite dev server and the Docker app.
    # Requests that change data from any other origin are rejected (CSRF protection).
    # In .env as JSON: CORS_ORIGINS=["http://localhost:5173","http://192.168.1.10:8080"]
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    @field_validator("anthropic_effort", mode="before")
    @classmethod
    def _empty_effort_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origin(cls, origins: list[str]) -> list[str]:
        # CORS would read "*" as "every origin", the CSRF check as a literal string - so
        # every write from a browser would get 403. List the origins instead.
        if "*" in origins:
            raise ValueError('"*" is not supported - list each allowed origin')
        return origins

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def models_cache_dir(self) -> Path:
        return self.models_dir or self.data_dir / "models"


@lru_cache
def get_settings() -> Settings:
    return Settings()
