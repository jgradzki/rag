import pytest

from app.config import Settings

LANGSMITH_VARIABLES = [
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_ENDPOINT",
]


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Settings(_env_file=None) skips backend/.env, but still reads the environment: an
    exported CORS_ORIGINS or LLM_PROVIDER in the developer's shell would change the
    tests. Remove every variable a Settings field reads; a test may set its own. LangSmith
    tracing too: LangChain would send every test prompt to the LangSmith service."""
    for name in [*(f.upper() for f in Settings.model_fields), *LANGSMITH_VARIABLES]:
        monkeypatch.delenv(name, raising=False)
