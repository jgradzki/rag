"""Chat model factory - the only place that knows which LLM provider is used."""

from langchain_core.language_models import BaseChatModel

from app.config import Settings


def create_llm(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # The key comes from backend/.env (Settings); without it the SDK falls back to
        # the ANTHROPIC_API_KEY environment variable.
        key = settings.anthropic_api_key
        effort = settings.anthropic_effort
        return ChatAnthropic(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            **({"output_config": {"effort": effort}} if effort else {}),
            **({"api_key": key} if key else {}),
        )

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            reasoning=settings.ollama_reasoning,
        )

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def describe_llm(settings: Settings) -> str:
    if settings.llm_provider == "anthropic":
        return f"Claude ({settings.anthropic_model})"
    return f"Ollama ({settings.ollama_model})"
