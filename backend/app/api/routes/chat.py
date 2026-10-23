import logging
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.api.deps import RagDep
from app.api.schemas import ChatRequest
from app.api.sse import sse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE stream: sources, token..., error?, done",
            "content": {"text/event-stream": {}},
        }
    },
)
async def chat(req: ChatRequest, rag: RagDep):
    # Embedding + vector search is CPU-bound and synchronous - keep it off the event loop.
    chunks = await run_in_threadpool(rag.retrieve, req.question)

    async def events() -> AsyncIterator[str]:
        yield sse("sources", [asdict(c) for c in chunks])
        try:
            async for token in rag.stream_answer(req.question, chunks):
                yield sse("token", token)
        except Exception as e:  # surface LLM errors (bad key, Ollama down) in the UI
            logger.exception("LLM call failed")
            yield sse("error", f"{type(e).__name__}: {e}")
        yield sse("done", None)

    return StreamingResponse(events(), media_type="text/event-stream")
