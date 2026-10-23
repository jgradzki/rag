from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.api.schemas import Health
from app.rag.llm import describe_llm

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(settings: SettingsDep) -> Health:
    return Health(status="ok", llm=describe_llm(settings), embedding_model=settings.embedding_model)
