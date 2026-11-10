"""
FACTORY PATTERN (Week 11): the one place that decides which AIProvider object to
create and how its library client is set up. AIManager asks the factory for a
provider by name, so it doesn't need to know how Gemini or Groq clients are built.
"""
from __future__ import annotations

from google import genai
from groq import Groq

from ai.ai_provider import AIProvider
from ai.gemini_provider import GeminiProvider
from ai.groq_provider import GroqProvider


class AIProviderFactory:
    """Creates AIProvider objects (SRP: creating providers is its only job)."""

    @staticmethod
    def create(provider_name: str, api_key: str | None, timeout_seconds: int) -> AIProvider:
        """Return the provider called provider_name ("gemini" or "groq").
        A missing API key gives a provider with no client (is_available is False).
        Raises ValueError for an unknown provider name."""
        if provider_name == "gemini":
            client = None
            if api_key:
                # Gemini takes its timeout in milliseconds.
                client = genai.Client(api_key=api_key,
                                      http_options={"timeout": timeout_seconds * 1000})
            return GeminiProvider(client)
        elif provider_name == "groq":
            client = None
            if api_key:
                # Groq takes its timeout in seconds.
                client = Groq(api_key=api_key, timeout=timeout_seconds)
            return GroqProvider(client)
        else:
            raise ValueError(f"Unknown AI provider: {provider_name}")
