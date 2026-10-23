import pytest
from langchain_ollama import ChatOllama

from app.config import Settings
from app.rag.llm import create_llm


def test_anthropic_key_from_settings_reaches_the_client(monkeypatch):
    # backend/.env is read by Settings only - it is not exported to the environment.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="sk-test")
    assert create_llm(settings).anthropic_api_key.get_secret_value() == "sk-test"


def test_anthropic_key_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    settings = Settings(_env_file=None, llm_provider="anthropic")
    assert create_llm(settings).anthropic_api_key.get_secret_value() == "sk-from-env"


def test_invalid_anthropic_effort_fails_at_startup():
    with pytest.raises(ValueError, match="anthropic_effort"):
        Settings(_env_file=None, anthropic_effort="Low")


def test_ollama_llm_gets_its_settings():
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        ollama_model="llama3.2",
        ollama_base_url="http://ollama:11434",
        ollama_reasoning=False,
    )
    llm = create_llm(settings)  # no network call until the first request
    assert isinstance(llm, ChatOllama)
    assert (llm.model, llm.base_url, llm.reasoning) == ("llama3.2", "http://ollama:11434", False)


def test_anthropic_effort_and_max_tokens_are_configurable():
    settings = Settings(
        _env_file=None,
        llm_provider="anthropic",
        anthropic_api_key="sk-test",
        anthropic_effort="",
        anthropic_max_tokens=4096,
    )
    llm = create_llm(settings)
    assert llm.max_tokens == 4096
    assert not llm.output_config  # empty ANTHROPIC_EFFORT = the parameter is not sent
