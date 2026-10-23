"""FastAPI application: wires the RAG pipeline (app.rag) to the HTTP API (app.api)."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.guards import RequestGuard
from app.api.routes import chat, documents, health
from app.config import Settings, get_settings
from app.rag.embeddings import FastEmbedEmbeddings
from app.rag.ingest import SUPPORTED_EXTENSIONS
from app.rag.llm import create_llm
from app.rag.service import RagService

logger = logging.getLogger(__name__)


def build_service(settings: Settings) -> RagService:
    return RagService(
        llm=create_llm(settings),
        embeddings=FastEmbedEmbeddings(
            settings.embedding_model, cache_dir=settings.models_cache_dir
        ),
        persist_dir=settings.chroma_dir,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        top_k=settings.top_k,
        min_relevance=settings.min_relevance,
        fetch_k=settings.fetch_k,
        mmr_lambda=settings.mmr_lambda,
    )


def index_sample_docs(service: RagService, sample_dir: Path) -> None:
    for path in sorted(sample_dir.glob("*")):
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            info = service.add_file(path, path.name)
            logger.info("Indexed sample %s (%d chunks)", info.name, info.chunks)


def create_app(settings: Settings | None = None, service: RagService | None = None) -> FastAPI:
    """Build the app. uvicorn calls it on start (`app.main:create_app --factory`), so
    importing this module - as the tests do - doesn't read backend/.env."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or build_service(settings)
        # Only on the first start: a user who deleted the samples doesn't get them back.
        # The marker lives in the index folder, so deleting the index resets it too.
        marker = settings.chroma_dir / "samples_indexed"
        if settings.index_samples_on_startup and not marker.exists():
            if app.state.service.is_empty():
                index_sample_docs(app.state.service, settings.sample_docs_dir)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        yield

    app = FastAPI(title="RAG demo", lifespan=lifespan)
    app.state.settings = settings
    # The guard is added first, so CORS wraps it (the last added runs first) and its
    # 403/411/413 answers carry CORS headers - readable by allowed browser origins.
    app.add_middleware(RequestGuard, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (health, documents, chat):
        app.include_router(module.router)
    return app


logging.basicConfig(level=logging.INFO)
