"""
ai_manager.py -- the AI Manager (the app's "core engine").

Pipeline: IOManager -> AIManager -> LogicManager -> DataManager.
For one maintenance check: build the prompt -> ask an AI -> parse the reply ->
validate it. AIManager.process() runs all four steps; the classes that do each
step are in the ai/ folder (one class per file).
Gemini (manual PDF attached) is the main AI; Groq (text excerpt of the manual)
is the backup; if both fail, FALLBACK_ASSESSMENT -> "NEEDS MANUAL REVIEW".
No business rules here, and errors go to the log, never print().
"""
from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv

from ai.ai_provider import AIProvider
from ai.ai_provider_factory import AIProviderFactory
from ai.prompt_builder import PromptBuilder
from ai.response_validator import ResponseValidator

logger = logging.getLogger("ai_manager")


class AIManager:
    """Runs one check through the AI pipeline, with retry and fallback (C2).

    AGGREGATION: the providers are created outside (by AIProviderFactory or a test)
    and passed in; they exist independently of this manager.
    COMPOSITION: the PromptBuilder and ResponseValidator are created here and owned.
    POLYMORPHISM / STRATEGY PATTERN: ask() calls provider.ask() on each provider in
    the same way, whether it is Gemini, Groq or any other AIProvider subclass, so a
    new AI can be added without changing this class (OCP)."""

    API_TIMEOUT_SECONDS = 60
    RETRY_DELAY_SECONDS = 3      # pause before retrying when no AI replied

    # Used when no AI gives a valid answer. ai_status != "ok" makes LogicManager.route
    # return "NEEDS MANUAL REVIEW", so the app carries on instead of crashing.
    FALLBACK_ASSESSMENT = {
        "urgency_score": None,
        "confidence": "Unknown",
        "overdue_summary": "AI assessment unavailable.",
        "recommended_action": "Could not get an AI recommendation -- check this part manually.",
        "manual_reference": "n/a",
        "ai_provider": "none",
        "ai_status": "unavailable",
    }

    def __init__(self, providers: list[AIProvider], max_attempts: int = 2,
                 retry_delay: float = RETRY_DELAY_SECONDS):
        self.__providers = list(providers)        # tried in this order
        self.__max_attempts = max_attempts
        self.__retry_delay = retry_delay
        self.__prompt_builder = PromptBuilder()
        self.__validator = ResponseValidator()

    @classmethod
    def from_env(cls) -> AIManager:
        """Create the Gemini and Groq providers from the API keys in .env, using the
        AIProviderFactory. A missing key gives a provider with no client."""
        load_dotenv()
        gemini_key = os.environ.get("GEMINI_API_KEY")
        groq_key = os.environ.get("GROQ_API_KEY")
        if not gemini_key:
            logger.error("GEMINI_API_KEY is not set -- copy .env.example to .env and add your key.")
        # A missing Groq key is not logged: Groq is only the backup.
        return cls([AIProviderFactory.create("gemini", gemini_key, cls.API_TIMEOUT_SECONDS),
                    AIProviderFactory.create("groq", groq_key, cls.API_TIMEOUT_SECONDS)])

    @property
    def providers(self) -> list[AIProvider]:
        """A copy of the provider list, in the order they are tried."""
        return list(self.__providers)

    def ask(self, prompt: str, manual_path: str | None, part_name: str = "") -> tuple:
        """Ask each provider in turn; the first reply wins.
        Returns (reply text or None, provider name such as "Gemini", or "none")."""
        for index, provider in enumerate(self.__providers):
            if not provider.is_available:
                continue
            if index > 0:
                # e.g. "Gemini unavailable -- trying the Groq backup."
                logger.warning("%s unavailable -- trying the %s.",
                               self.__providers[index - 1].name, provider.log_name)
            reply = provider.ask(prompt, manual_path, part_name)   # polymorphic call
            if reply is not None:
                return reply, provider.name
        return None, "none"

    def process(self, record: dict, manual_path: str | None = None) -> dict:
        """C2: run every new maintenance check through the AI, validating each
        provider's reply. If one provider's reply is missing or malformed, the next
        provider is tried at once instead of asking the first one again. The whole
        round is tried up to max_attempts times. Returns a copy of the record with the
        AI's answer, or FALLBACK_ASSESSMENT values if no valid answer was obtained."""
        prompt = self.__prompt_builder.build(record)
        expect_history = PromptBuilder.has_brake_history(record)

        for attempt in range(1, self.__max_attempts + 1):
            for index, provider in enumerate(self.__providers):
                if not provider.is_available:
                    continue
                if index > 0:
                    # e.g. "No valid Gemini assessment -- trying Groq backup."
                    logger.warning("No valid %s assessment -- trying %s.",
                                   self.__providers[index - 1].name, provider.log_name)
                # POLYMORPHISM: the same ask() call works for every provider.
                reply = provider.ask(prompt, manual_path, record.get("part_name", ""))
                # Even if a provider returns text, invalid JSON or missing fields mean failure.
                answer = self.__validator.validate(self.__validator.parse(reply),
                                                   expect_history=expect_history)
                if answer is not None:
                    answer["ai_provider"] = provider.name      # shown as "Answered by"
                    result = dict(record)
                    result.update(answer)
                    return result

            logger.warning("All AI providers failed validation (attempt %d of %d).",
                           attempt, self.__max_attempts)
            if attempt < self.__max_attempts:
                time.sleep(self.__retry_delay)

        # All AI responses failed, so LogicManager.route will request manual review.
        result = dict(record)
        result.update(self.FALLBACK_ASSESSMENT)
        return result
