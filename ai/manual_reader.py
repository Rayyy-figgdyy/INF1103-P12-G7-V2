"""
Reads the text of a manual PDF and keeps only the lines about one part
(for the Groq backup, which can't read PDF files).
"""
from __future__ import annotations

import logging

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

# Logged under the AI Manager's name, so its messages read "ai_manager: ...".
logger = logging.getLogger("ai_manager")


class ManualReader:
    """Gets the text of a manual PDF and keeps only the lines about one part.
    Encapsulation: callers just ask for text()/excerpt(); how pdfplumber is used
    and how lines are picked stays inside this class."""

    # Groq error 413, limit manual text sent to Groq
    MAX_MANUAL_CHARS = 8_000

    # Find the relevant alternative names for car parts in the manual
    PART_SEARCH_WORDS = {
        "Engine Oil":        ["engine oil", "oil filter", "oil and filter"],
        "Brake Pads":        ["brake pad", "brake disc", "brakes"],
        "Spark Plugs":       ["spark plug"],
        "Tyres":             ["tyre", "tire rotation", "tires", "rotate"],
        "Engine Air Filter": ["air cleaner", "air filter"],
        "Coolant":           ["coolant", "cooling system"],
    }

    def text(self, manual_path: str) -> str:
        """Extract all text from the manual PDF (Groq cannot read PDF files).
        Returns the text, or "" if the PDF is unreadable or has no text layer."""
        try:
            page_texts = []
            with pdfplumber.open(manual_path) as pdf:
                for page in pdf.pages:
                    page_texts.append(page.extract_text() or "")
            text = "\n".join(page_texts).strip()
        except (OSError, PdfminerException) as error:
            # OSError: the file is missing or can't be opened.
            # PdfminerException: the file isn't a readable PDF.
            logger.error("Could not read text from %s: %s", manual_path, error)
            return ""
        if not text:
            logger.warning("No text found in %s (is it a scanned image?).", manual_path)
        return text

    def excerpt(self, text: str, part_name: str) -> str:
        """Keep only the manual lines that mention the part (plus one line either side).
        Returns at most MAX_MANUAL_CHARS characters; uses the manual's start if no match."""
        # Parts not in PART_SEARCH_WORDS fall back to the words of their own name.
        if part_name in self.PART_SEARCH_WORDS:
            search_words = self.PART_SEARCH_WORDS[part_name]
        else:
            search_words = []
            for word in part_name.split():
                if len(word) > 2:
                    search_words.append(word.lower().rstrip("s"))

        lines = text.splitlines()

        # Neighbouring lines are kept because schedule tables often wrap onto two lines
        lines_to_keep = set()
        for line_number in range(len(lines)):
            line = lines[line_number].lower()
            for word in search_words:
                if word in line:
                    lines_to_keep.update({line_number - 1, line_number, line_number + 1})

        kept_lines = []
        for line_number in sorted(lines_to_keep):
            if 0 <= line_number < len(lines):
                kept_lines.append(lines[line_number])

        excerpt = "\n".join(kept_lines)
        if not excerpt:
            excerpt = text
        # Stop Groq refusing the request with error 413
        if len(excerpt) > self.MAX_MANUAL_CHARS:
            logger.warning("Manual text cut to %d characters for the backup AI.",
                           self.MAX_MANUAL_CHARS)
            excerpt = excerpt[:self.MAX_MANUAL_CHARS]
        return excerpt
