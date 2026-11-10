"""
<<abstract>> AIProvider: one AI service. Shared behaviour lives here (ask());
each subclass implements _send() for its own service.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

# Logged under the AI Manager's name, so its messages read "ai_manager: ...".
logger = logging.getLogger("ai_manager")


class AIProvider(ABC):
    """ABSTRACT CLASS for one AI service (is-a relationship: Gemini is-a AIProvider).
    It cannot be created itself.

    Shared behaviour: ask() holds the steps every provider shares (skip if there is
    no client, call the service, turn a failure into a log line + None). Each
    subclass only implements _send(), the part that talks to its own service, and
    overrides EXPECTED_ERRORS with the errors its own library raises."""

    DEFAULT_MODEL = ""       # set by each subclass
    MODEL_ENV_VAR = ""       # .env variable that can override the model
    EXPECTED_ERRORS = ()     # the errors this service is known to raise (subclasses override)

    def __init__(self, client, model: str | None = None):
        # Encapsulation: _client and _model are PROTECTED (one underscore, # in UML):
        # the subclasses use them in _send(), but other classes must not.
        self._client = client
        self._model = model or os.environ.get(self.MODEL_ENV_VAR) or self.DEFAULT_MODEL

    @property
    @abstractmethod
    def name(self) -> str:
        """The label saved with the result and shown as "Answered by"."""

    @property
    def log_name(self) -> str:
        """How the provider is named in log messages (subclasses may override)."""
        return self.name

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        """False when there was no API key, so no client could be created."""
        return self._client is not None

    def ask(self, prompt: str, manual_path: str | None, part_name: str = "") -> str | None:
        """Send the prompt (and the manual) to this AI.
        Returns the reply text, or None if there is no client or the call fails."""
        if not self.is_available:
            return None
        try:
            return self._send(prompt, manual_path, part_name)
        except self.EXPECTED_ERRORS as error:
            # A known failure (no network, bad key, 503 busy, 429 rate limit, timeout):
            # log it and return None, so AIManager moves on to the next provider.
            logger.error("%s call failed: %s", self.log_name, error)
            return None
        except Exception as error:
            # Last resort, only at this boundary with an outside library: an error type
            # we didn't expect must not crash the app in the middle of a check.
            logger.error("%s call failed (%s): %s", self.log_name, type(error).__name__, error)
            return None

    @abstractmethod
    def _send(self, prompt: str, manual_path: str | None, part_name: str) -> str | None:
        """Call the service and return its reply text. Errors may be raised;
        ask() catches them."""
