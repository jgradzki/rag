"""Request and response bodies of the API (they also document it at /docs)."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints


class ChatRequest(BaseModel):
    # Whitespace is stripped first, so a question of only spaces is rejected (422).
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


class Health(BaseModel):
    status: str
    llm: str
    embedding_model: str


class Deleted(BaseModel):
    deleted: str
