"""
Core PDF parser for Macedonian Parliament stenographic notes.
"""

from __future__ import annotations

import re
from pathlib import Path
from collections import defaultdict
from typing import Optional

import pdfplumber
from pdfplumber.page import Page

from ..config import ParserConfig
from ..models import Speech
from ..utils import get_logger
from .layout import VerticalProjectionDetector
from .cleaning import FooterCleaner, TextBuffer

logger = get_logger()


class SobranieParser:
    """Two-column parser with complete footer cleaning."""

    CYRILLIC_UPPER_START = 0x0410
    CYRILLIC_UPPER_END = 0x042F
    SPECIAL_MACEDONIAN_UPPER = {0x0403, 0x0405, 0x0408, 0x0409, 0x040A, 0x040C, 0x040F}

    POISON_WORDS = {
        "следното", "вкупно", "износ", "камата", "транша", "повлекување",
        "отплата", "главница", "денари", "евра", "процент", "година", "години",
        "гласаа", "против", "воздржани", "предлог", "закон", "член",
        "точка", "амандман", "седница", "дневен", "записник", "верификација",
        "констатирам", "усвоени", "известени", "поканети", "дека", "собранието",
        "владата", "пратениците", "вели", "вика", "рече", "кажа", "во",
        "овој", "контекст", "еве"
    }

    def __init__(self, config: Optional[ParserConfig] = None):
        """
        Initialize the parser.

        Args:
            config: Parser configuration
        """
        self.config = config or ParserConfig()
        self.detector = VerticalProjectionDetector(self.config)
        self._buffer = TextBuffer()
        self._stats = defaultdict(int)

    def _is_cyrillic_uppercase(self, char: str) -> bool:
        """Check if character is Cyrillic uppercase."""
        code = ord(char)
        return (self.CYRILLIC_UPPER_START <= code <= self.CYRILLIC_UPPER_END or
                code in self.SPECIAL_MACEDONIAN_UPPER)

    def _is_valid_speaker_name(self, name: str) -> bool:
        """Validate if a string looks like a valid speaker name."""
        name = name.strip()
        if len(name) < 3 or len(name) > 50:
            return False
        words = name.split()
        if len(words) > 6:
            return False
        if not self._is_cyrillic_uppercase(name[0]):
            return False
        if re.search(r'\d', name):
            return False
        # Check last word starts with uppercase
        last_word = words[-1]
        last_word_clean = last_word.strip(".,-")
        if last_word_clean:
            if not self._is_cyrillic_uppercase(last_word_clean[0]):
                return False
        # Check poison words (exact match using split)
        name_words_lower = {w.lower() for w in name.split()}
        for poison in self.POISON_WORDS:
            if poison in name_words_lower:
                self._stats["speakers_poisoned"] += 1
                return False
        return True

    def _extract_words(self, page: Page) -> list[dict]:
        """Extract words from a page, filtering out footer elements."""
        all_words = page.extract_words(
            keep_blank_chars=False,
            x_tolerance=2,
            y_tolerance=2
        ) or []
        if not all_words:
            return []
        page_height = page.height
        footer_boundary = page_height * (1 - self.config.FOOTER_ZONE_RATIO)
        content_words = []
        for word in all_words:
            word_bottom = word.get("bottom", word["top"])
            text = word["text"].strip()
            if word_bottom >= footer_boundary:
                if FooterCleaner.is_footer_code(text):
                    self._stats["footer_codes_removed"] += 1
                    continue
                if FooterCleaner.is_page_number_at_bottom(text):
                    self._stats["page_numbers_removed"] += 1
                    continue
            if FooterCleaner.is_footer_code(text):
                self._stats["footer_codes_removed"] += 1
                continue
            content_words.append(word)
        return content_words

    def _split_into_columns(
            self,
            words: list[dict],
            gutter_center: float
    ) -> tuple[list[dict], list[dict]]:
        """Split words into left and right columns."""
        left_words = []
        right_words = []
        margin = self.config.COLUMN_MARGIN
        for word in words:
            word_center = (word["x0"] + word["x1"]) / 2
            if word_center < gutter_center - margin:
                left_words.append(word)
            elif word_center > gutter_center + margin:
                right_words.append(word)
        return left_words, right_words

    def _reconstruct_lines(self, words: list[dict]) -> list[str]:
        """Reconstruct text lines from word positions."""
        if not words:
            return []
        sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
        lines = []
        current_line = [sorted_words[0]]
        current_top = sorted_words[0]["top"]
        for word in sorted_words[1:]:
            if abs(word["top"] - current_top) <= self.config.Y_TOLERANCE:
                current_line.append(word)
            else:
                current_line.sort(key=lambda w: w["x0"])
                line_text = " ".join(w["text"] for w in current_line)
                lines.append(line_text)
                current_line = [word]
                current_top = word["top"]
        if current_line:
            current_line.sort(key=lambda w: w["x0"])
            lines.append(" ".join(w["text"] for w in current_line))
        cleaned_lines = []
        for line in lines:
            cleaned = re.sub(r"\s+", " ", line).strip()
            cleaned = FooterCleaner.clean_text(cleaned)
            if cleaned:
                cleaned_lines.append(cleaned)
        return cleaned_lines

    def _try_extract_speaker(self, line: str) -> Optional[tuple[str, str]]:
        """Extract speaker from start of line."""
        if ":" not in line:
            return None
        parts = line.split(":", 1)
        before = parts[0].strip()
        after = parts[1].strip() if len(parts) > 1 else ""
        if self._is_valid_speaker_name(before):
            return (before, after)
        return None

    def _try_extract_speaker_mid_line(self, line: str) -> Optional[tuple[str, str, str]]:
        """
        Detect speaker starting in the middle of a line.

        Returns: (text_before, speaker_name, text_after) or None
        """
        pattern = re.compile(
            r'([.?!])\s+'
            r'([А-ЯЃЅЈЉЊЌЏа-яѓѕјљњќџ][А-ЯЃЅЈЉЊЌЏа-яѓѕјљњќџ\s\-\.]+?)'
            r'\s*:\s*'
            r'(.+)$'
        )

        match = pattern.search(line)
        if match:
            full_match_start = match.start()
            speaker_candidate = match.group(2).strip()
            text_after = match.group(3).strip()

            if self._is_valid_speaker_name(speaker_candidate):
                text_before = line[:full_match_start + 1].strip()
                return (text_before, speaker_candidate, text_after)

        return None

    def _clean_text(self, text: str) -> str:
        """Clean text by removing parenthetical content and footer patterns."""
        cleaned = re.sub(r'\([^)]*\)', ' ', text)
        cleaned = FooterCleaner.clean_text(cleaned)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _process_line(self, line: str, page_num: int, column: str) -> list[Speech]:
        """Process a line, handling both start and mid-line speakers."""
        completed_speeches = []

        if not line.strip():
            return completed_speeches
        if re.match(r'^[\s\.\,\-\_\(\)/]+$', line):
            return completed_speeches
        if FooterCleaner.is_footer_code(line.strip()):
            self._stats["footer_lines_removed"] += 1
            return completed_speeches

        self._stats["lines_processed"] += 1

        # First, check for speaker at start of line
        result = self._try_extract_speaker(line)

        if result:
            speaker, rest = result
            self._stats["speakers_found"] += 1
            logger.debug(f"  [{column}] ✓ Speaker (start): '{speaker}'")

            # Check if there's another speaker mid-line in the rest
            mid_line_result = self._try_extract_speaker_mid_line(rest)

            if mid_line_result:
                text_before, mid_speaker, text_after = mid_line_result

                previous = self._buffer.start_new(
                    speaker=speaker,
                    page=page_num,
                    initial_text=self._clean_text(text_before)
                )
                if previous and len(previous.raw_text) >= self.config.MIN_SPEECH_LENGTH:
                    completed_speeches.append(previous)

                self._stats["speakers_found"] += 1
                logger.debug(f"  [{column}] ✓ Speaker (mid): '{mid_speaker}'")

                previous = self._buffer.start_new(
                    speaker=mid_speaker,
                    page=page_num,
                    initial_text=self._clean_text(text_after)
                )
                if previous and len(previous.raw_text) >= self.config.MIN_SPEECH_LENGTH:
                    completed_speeches.append(previous)
            else:
                previous = self._buffer.start_new(
                    speaker=speaker,
                    page=page_num,
                    initial_text=self._clean_text(rest)
                )
                if previous and len(previous.raw_text) >= self.config.MIN_SPEECH_LENGTH:
                    completed_speeches.append(previous)
        else:
            mid_line_result = self._try_extract_speaker_mid_line(line)

            if mid_line_result:
                text_before, mid_speaker, text_after = mid_line_result

                if not self._buffer.is_empty():
                    cleaned_before = self._clean_text(text_before)
                    if cleaned_before:
                        self._buffer.append(cleaned_before, page_num)

                self._stats["speakers_found"] += 1
                logger.debug(f"  [{column}] ✓ Speaker (mid): '{mid_speaker}'")

                previous = self._buffer.start_new(
                    speaker=mid_speaker,
                    page=page_num,
                    initial_text=self._clean_text(text_after)
                )
                if previous and len(previous.raw_text) >= self.config.MIN_SPEECH_LENGTH:
                    completed_speeches.append(previous)
            else:
                if not self._buffer.is_empty():
                    cleaned = self._clean_text(line)
                    if cleaned:
                        self._buffer.append(cleaned, page_num)

        return completed_speeches

    def _process_page(self, page: Page, page_num: int) -> list[Speech]:
        """Process a single page."""
        speeches = []
        all_words = self._extract_words(page)
        if not all_words:
            logger.warning(f"Page {page_num}: No words extracted")
            return speeches
        self._stats["total_words"] += len(all_words)
        gutter = self.detector.detect(all_words, page.width, page_num)
        if gutter and gutter.confidence > 0.3:
            gutter_center = gutter.center_x
            logger.debug(f"Page {page_num}: Gutter at x={gutter_center:.1f}")
            self._stats["pages_with_gutter"] += 1
        else:
            gutter_center = page.width * self.config.FALLBACK_GUTTER_RATIO
            logger.debug(f"Page {page_num}: Center gutter at {gutter_center:.1f}")
            self._stats["pages_fallback"] += 1
        left_words, right_words = self._split_into_columns(all_words, gutter_center)
        self._stats["left_column_words"] += len(left_words)
        self._stats["right_column_words"] += len(right_words)

        # LEFT column
        left_lines = self._reconstruct_lines(left_words)
        for line in left_lines:
            line_speeches = self._process_line(line, page_num, "L")
            speeches.extend(line_speeches)

        # RIGHT column
        right_lines = self._reconstruct_lines(right_words)
        for line in right_lines:
            line_speeches = self._process_line(line, page_num, "R")
            speeches.extend(line_speeches)

        self._stats["pages_processed"] += 1
        return speeches

    def parse(self, pdf_path: str | Path) -> list[Speech]:
        """
        Parse a PDF file and extract speeches.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of Speech objects
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        all_speeches = []
        self._buffer = TextBuffer()
        self._stats = defaultdict(int)
        logger.info("=" * 70)
        logger.info(f"PARSING: {pdf_path.name}")
        logger.info("=" * 70)
        with pdfplumber.open(pdf_path) as pdf:
            logger.info(f"Total pages: {len(pdf.pages)}")
            for page_num, page in enumerate(pdf.pages, 1):
                speeches = self._process_page(page, page_num)
                all_speeches.extend(speeches)
        final = self._buffer.flush()
        if final and len(final.raw_text) >= self.config.MIN_SPEECH_LENGTH:
            all_speeches.append(final)
        self._print_summary(all_speeches)
        return all_speeches

    def _print_summary(self, speeches: list[Speech]) -> None:
        """Print parsing summary."""
        logger.info("-" * 70)
        logger.info("PARSER SUMMARY")
        logger.info("-" * 70)
        logger.info(f"Pages processed:       {self._stats['pages_processed']}")
        logger.info(f"Total words:          {self._stats['total_words']}")
        logger.info(f"Speakers found:       {self._stats['speakers_found']}")
        logger.info(f"TOTAL SPEECHES:        {len(speeches)}")
        logger.info("-" * 70)

    def parse_to_jsonl(self, pdf_path: str | Path, output_path: str | Path) -> int:
        """
        Parse a PDF and save results to JSONL file.

        Args:
            pdf_path: Path to the PDF file
            output_path: Path for the output JSONL file

        Returns:
            Number of speeches extracted
        """
        speeches = self.parse(pdf_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for speech in speeches:
                f.write(speech.to_json() + "\n")
        logger.info(f"Wrote {len(speeches)} speeches to {output_path}")
        return len(speeches)