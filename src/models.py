"""
Data models for Sobranie Bot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, NamedTuple


class GutterInfo(NamedTuple):
    """Information about detected column gutter."""
    start_x: float
    end_x: float
    center_x: float
    width: float
    confidence: float


@dataclass
class Speech:
    """Represents a single speech extracted from stenographic notes."""
    speaker: str
    raw_text: str
    source_page: int
    end_page: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert speech to dictionary."""
        result = {
            "speaker": self.speaker,
            "raw_text": self.raw_text,
            "source_page": self.source_page
        }
        if self.end_page and self.end_page != self.source_page:
            result["end_page"] = self.end_page
        return result

    def to_json(self) -> str:
        """Convert speech to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)