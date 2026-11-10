"""
The backup AI. INHERITANCE: Groq is-a AIProvider. COMPOSITION: it creates and
owns a ManualReader, because Groq can't read PDF files itself.
"""
from __future__ import annotations

import groq

from ai.ai_provider import AIProvider
from ai.manual_reader import ManualReader


class GroqProvider(AIProvider):
    """INHERITANCE: the backup AI. Groq can't read PDFs, so it gets a text excerpt.
    COMPOSITION: it creates and owns its own ManualReader."""

    # Overrides the parent's EXPECTED_ERRORS: groq.APIError covers connection
    # errors, timeouts and error replies such as 429 rate limit.
    EXPECTED_ERRORS = (groq.APIError,)

    DEFAULT_MODEL = "openai/gpt-oss-120b"
    MODEL_ENV_VAR = "GROQ_MODEL"
    MAX_ANSWER_TOKENS = 2048

    def __init__(self, client, model: str | None = None):
        super().__init__(client, model)            # the parent sets up _client and _model
        self.__manual_reader = ManualReader()      # composition: created and owned here

    @property
    def name(self) -> str:
        return "Groq (backup)"

    @property
    def log_name(self) -> str:                     # overrides the parent's log_name
        return "Groq backup"

    def _send(self, prompt: str, manual_path: str | None, part_name: str) -> str | None:
        content = prompt
        if manual_path:
            manual = self.__manual_reader.excerpt(self.__manual_reader.text(manual_path), part_name)
            if manual:
                content = ("OWNER'S MANUAL (the sections about this part, extracted from the PDF):\n"
                           + manual + "\n\n" + prompt)
            else:
                content = "(The owner's manual could not be read for this request.)\n\n" + prompt
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            temperature=0,                                     # Repeatable answers
            max_completion_tokens=self.MAX_ANSWER_TOKENS,
            reasoning_effort="low",                            # Keep response short
            stream=False,
        )
        return response.choices[0].message.content
