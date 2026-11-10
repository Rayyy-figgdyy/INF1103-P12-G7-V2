"""
The main AI. INHERITANCE: Gemini is-a AIProvider; it overrides _send() and
EXPECTED_ERRORS.
"""
from __future__ import annotations

import httpx
from google.genai import errors as genai_errors

from ai.ai_provider import AIProvider


class GeminiProvider(AIProvider):
    """INHERITANCE: the main AI. Gemini reads the whole manual PDF itself."""

    # Overrides the parent's EXPECTED_ERRORS: errors from the Gemini service
    # (APIError, e.g. bad key or 503 busy), the network (httpx), a bad reply
    # (ValueError) and the manual upload (OSError, e.g. file missing).
    EXPECTED_ERRORS = (genai_errors.APIError, httpx.HTTPError, ValueError, OSError)

    DEFAULT_MODEL = "gemini-3.6-flash"
    MODEL_ENV_VAR = "GEMINI_MODEL"
    CONFIG = {
        # C4: temperature 0 reduces response variability; repeated saved checks reuse stored results.
        "temperature": 0,
        # C3: ask for a JSON-only reply so ResponseValidator.parse() can read it.
        "response_mime_type": "application/json",
        # The SDK can run our Python functions for the AI; we pass none, so it is
        # switched off and the AI only answers the question.
        "automatic_function_calling": {"disable": True},
    }

    @property
    def name(self) -> str:
        return "Gemini"

    def _send(self, prompt: str, manual_path: str | None, part_name: str) -> str | None:
        contents = [prompt]
        if manual_path:
            # The PDF is uploaded for Gemini to read and base its answer on this car's manual
            uploaded_manual = self._client.files.upload(file=manual_path)
            contents = [uploaded_manual, prompt]
        response = self._client.models.generate_content(
            model=self._model, contents=contents, config=self.CONFIG)
        return response.text
