"""
Text cleaning utilities for PDF parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models import Speech


class FooterCleaner:
    """Removes archival footer codes while preserving speech numbers."""

    FOOTER_CODE_PATTERNS = [
        re.compile(r'^\d{1,3}-\d{1,3}/\d{1,3}$'),
        re.compile(r'^\d{1,3}-\d{1,3}/\d{1,3}\.$'),
        re.compile(r'^\d{1,3}-\d{1,3}/\d{1,3},$'),
        re.compile(r'^\d{1,3}/\d{1,3}\.-$'),
        re.compile(r'^\d{1,3}-\d{1,3}/\d{1,3}\.-$'),
        re.compile(r'^\d{1,2}/\d{1,3}$'),
        re.compile(r'^\d{1,2}/\d{1,3}\.$'),
        re.compile(r'^\d{1,3}\.-$'),
        re.compile(r'^\d{1,3}-$'),
    ]

    INLINE_FOOTER_PATTERNS = [
        re.compile(r'\s+\d{1,3}-\d{1,3}/\d{1,3}[,.]?\s*$'),
        re.compile(r'\s+\d{1,2}/\d{1,3}\.?\-?\s*$'),
        re.compile(r'\s+\d{1,3}\.-\s*$'),
    ]

    @classmethod
    def is_footer_code(cls, text: str) -> bool:
        """Check if text is a footer code."""
        text = text.strip()
        if not text:
            return False
        for pattern in cls.FOOTER_CODE_PATTERNS:
            if pattern.match(text):
                return True
        return False

    @classmethod
    def is_page_number_at_bottom(cls, text: str) -> bool:
        """Check if text is a page number."""
        text = text.strip()
        if re.match(r'^\d{1,3}$', text):
            try:
                num = int(text)
                return 1 <= num <= 500
            except:
                return False
        return False

    @classmethod
    def clean_text(cls, text: str) -> str:
        """Remove inline footer patterns from text."""
        cleaned = text
        for pattern in cls.INLINE_FOOTER_PATTERNS:
            cleaned = pattern.sub('', cleaned)
        return cleaned.strip()


@dataclass
class TextBuffer:
    """Buffer for accumulating speech text across pages."""

    speaker: str = ""
    text_parts: list[str] = field(default_factory=list)
    start_page: int = 0
    current_page: int = 0

    def is_empty(self) -> bool:
        """Check if buffer has no speaker."""
        return not self.speaker

    def has_content(self) -> bool:
        """Check if buffer has speaker and text."""
        return bool(self.speaker and self.text_parts)

    def append(self, text: str, page: int) -> None:
        """Append text to the buffer."""
        text = text.strip()
        if not text:
            return
        if self.text_parts and self.text_parts[-1].endswith("-"):
            self.text_parts[-1] = self.text_parts[-1][:-1] + text
        else:
            self.text_parts.append(text)
        self.current_page = page

    def flush(self) -> Optional[Speech]:
        """Flush buffer and return a Speech object."""
        if not self.has_content():
            self._reset()
            return None
        merged = " ".join(self.text_parts)
        merged = re.sub(r"\s+", " ", merged).strip()
        merged = FooterCleaner.clean_text(merged)
        if not merged:
            self._reset()
            return None
        speech = Speech(
            speaker=self.speaker,
            raw_text=merged,
            source_page=self.start_page,
            end_page=self.current_page if self.current_page != self.start_page else None
        )
        self._reset()
        return speech

    def _reset(self) -> None:
        """Reset the buffer."""
        self.speaker = ""
        self.text_parts = []
        self.start_page = 0
        self.current_page = 0

    def start_new(self, speaker: str, page: int, initial_text: str = "") -> Optional[Speech]:
        """Start a new speech, flushing any previous content."""
        previous = self.flush()
        self.speaker = speaker
        self.start_page = page
        self.current_page = page
        if initial_text.strip():
            self.text_parts.append(initial_text.strip())
        return previous