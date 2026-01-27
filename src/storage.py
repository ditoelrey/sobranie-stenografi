"""
History management for Sobranie Bot.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from .utils import get_logger

logger = get_logger()


class HistoryManager:
    """Manages the history of processed sessions."""

    def __init__(self, history_file: Path):
        """
        Initialize the history manager.

        Args:
            history_file: Path to the history JSON file
        """
        self.history_file = history_file
        self._history: dict = self._load()

    def _load(self) -> dict:
        """Load history from file."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load history: {e}")
                return {"processed_sessions": {}}
        return {"processed_sessions": {}}

    def _save(self) -> None:
        """Save history to file."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self._history, f, ensure_ascii=False, indent=2)

    def is_processed(self, sitting_id: str) -> bool:
        """
        Check if a session has been processed.

        Args:
            sitting_id: The session ID to check

        Returns:
            True if already processed, False otherwise
        """
        return sitting_id in self._history.get("processed_sessions", {})

    def mark_processed(self, sitting_id: str, metadata: dict) -> None:
        """
        Mark a session as processed.

        Args:
            sitting_id: The session ID
            metadata: Additional metadata to store
        """
        if "processed_sessions" not in self._history:
            self._history["processed_sessions"] = {}
        self._history["processed_sessions"][sitting_id] = {
            "processed_at": datetime.now().isoformat(),
            **metadata
        }
        self._save()

    def get_stats(self) -> dict:
        """
        Get processing statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "total_processed": len(self._history.get("processed_sessions", {}))
        }