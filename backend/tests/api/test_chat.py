import pytest
from langchain_core.language_models import FakeListChatModel

from app.rag.prompts import NO_DOCUMENTS_ANSWER
from tests.api.utils import FAKE_ANSWER, make_client, parse_sse, upload


def test_chat_streams_sources_then_answer(client):
    upload(client, "mars.md", "Curiosity landed in Gale Crater in 2012.")

    res = client.post("/api/chat", json={"question": "Where did Curiosity land?"})
    events = parse_sse(res.text)

    assert events[0][0] == "sources"
    assert events[0][1][0]["source"] == "mars.md"
    assert events[0][1][0]["number"] == 1
    answer = "".join(data for name, data in events if name == "token")
    assert answer == FAKE_ANSWER
    assert events[-1] == ("done", None)


def test_chat_without_documents(client):
    events = parse_sse(client.post("/api/chat", json={"question": "Hello?"}).text)
    assert events[0] == ("sources", [])
    assert "".join(d for n, d in events if n == "token") == NO_DOCUMENTS_ANSWER


def test_chat_drops_chunks_below_min_relevance(tmp_path):
    with make_client(tmp_path, min_relevance=1.1) as client:  # nothing can pass
        upload(client, "mars.md", "Curiosity landed in Gale Crater in 2012.")
        events = parse_sse(client.post("/api/chat", json={"question": "Where?"}).text)

    assert events[0] == ("sources", [])
    # Documents exist, so the LLM still answers (and can say "not found" itself) -
    # but its "[1]" points at no source, so it is stripped.
    assert "".join(d for n, d in events if n == "token") == "Curiosity landed in Gale Crater."


@pytest.mark.parametrize(("error_on_chunk", "tokens_before_error"), [(5, True), (0, False)])
def test_chat_streams_llm_error_then_done(tmp_path, error_on_chunk, tokens_before_error):
    # A failing LLM (bad API key, Ollama down) must still end the stream cleanly.
    llm = FakeListChatModel(responses=[FAKE_ANSWER], error_on_chunk_number=error_on_chunk)
    with make_client(tmp_path, min_relevance=-1.0, llm=llm) as client:
        upload(client, "mars.md", "Curiosity landed in Gale Crater in 2012.")
        events = parse_sse(client.post("/api/chat", json={"question": "Where?"}).text)

    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert ("token" in names[: names.index("error")]) is tokens_before_error
    assert events[-2][0] == "error" and events[-2][1].startswith("FakeListChatModelError")
    assert events[-1] == ("done", None)


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_chat_rejects_empty_question(client, question):
    assert client.post("/api/chat", json={"question": question}).status_code == 422


@pytest.mark.parametrize(("length", "status"), [(4000, 200), (4001, 422)])
def test_chat_question_length_limit(client, length, status):
    # frontend/src/api.ts mirrors this limit (MAX_QUESTION_LENGTH)
    assert client.post("/api/chat", json={"question": "x" * length}).status_code == status
