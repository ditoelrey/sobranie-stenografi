"""
Layout detection for two-column PDF parsing.
"""

from __future__ import annotations

from typing import Optional

from ..models import GutterInfo
from ..config import ParserConfig


class VerticalProjectionDetector:
    """Detects the gutter (vertical gap) between two columns."""

    def __init__(self, config: ParserConfig):
        """
        Initialize the detector.

        Args:
            config: Parser configuration
        """
        self.config = config

    def detect(
            self,
            words: list[dict],
            page_width: float,
            page_num: int = 0
    ) -> Optional[GutterInfo]:
        """
        Detect the gutter between columns.

        Args:
            words: List of word dictionaries from pdfplumber
            page_width: Width of the page
            page_num: Page number (for logging)

        Returns:
            GutterInfo if gutter found, None otherwise
        """
        if len(words) < 10:
            return None

        resolution = self.config.DENSITY_MAP_RESOLUTION
        num_bins = int(page_width / resolution) + 1
        density = [0] * num_bins

        for word in words:
            start_bin = max(0, min(int(word["x0"] / resolution), num_bins - 1))
            end_bin = max(0, min(int(word["x1"] / resolution), num_bins - 1))
            for b in range(start_bin, end_bin + 1):
                density[b] += 1

        search_start = int((page_width * self.config.GUTTER_SEARCH_START) / resolution)
        search_end = int((page_width * self.config.GUTTER_SEARCH_END) / resolution)
        search_start = max(0, search_start)
        search_end = min(len(density) - 1, search_end)

        valleys = []
        valley_start = None

        for i in range(search_start, search_end + 1):
            if density[i] <= self.config.DENSITY_THRESHOLD:
                if valley_start is None:
                    valley_start = i
            else:
                if valley_start is not None:
                    valleys.append((valley_start, i - 1))
                    valley_start = None

        if valley_start is not None:
            valleys.append((valley_start, search_end))

        if not valleys:
            return None

        best = max(valleys, key=lambda v: v[1] - v[0])
        start_x = best[0] * resolution
        end_x = best[1] * resolution
        width = end_x - start_x

        if width < self.config.MIN_GUTTER_WIDTH:
            return None

        valley_density = density[best[0]:best[1] + 1]
        avg = sum(valley_density) / len(valley_density) if valley_density else 0
        confidence = max(0, 1.0 - (avg / max(self.config.DENSITY_THRESHOLD, 1)))

        return GutterInfo(start_x, end_x, (start_x + end_x) / 2, width, confidence)