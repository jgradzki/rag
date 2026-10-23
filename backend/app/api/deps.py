"""Dependencies the routes declare with Depends: the settings and the RAG service."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.rag.service import RagService


# Both live on app.state (set by create_app), so tests can build an app with their own.
def app_settings(request: Request) -> Settings:
    return request.app.state.settings


def rag_service(request: Request) -> RagService:
    return request.app.state.service


SettingsDep = Annotated[Settings, Depends(app_settings)]
RagDep = Annotated[RagService, Depends(rag_service)]
