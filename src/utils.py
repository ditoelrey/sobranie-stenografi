"""
Utility functions for Sobranie Bot.
"""

from __future__ import annotations

import re
import logging
from typing import Optional
from datetime import datetime

# Global logger instance (singleton pattern)
_logger: Optional[logging.Logger] = None


def setup_logger(
        name: str = "sobranie_bot",
        log_file: Optional[str] = None,
        level: int = logging.INFO
) -> logging.Logger:
    """
    Set up and configure the logger (singleton pattern).

    Args:
        name: Logger name
        log_file: Path to log file (optional)
        level: Logging level

    Returns:
        Configured logger instance
    """
    global _logger

    # Return existing logger if already configured
    if _logger is not None:
        return _logger

    # Create logger
    _logger = logging.getLogger(name)
    _logger.setLevel(level)

    # Avoid adding handlers multiple times
    if _logger.handlers:
        return _logger

    # Create formatters
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    # File handler (if log_file provided)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)

    return _logger


def get_logger() -> logging.Logger:
    """
    Get the configured logger instance.

    Returns:
        Logger instance (creates default if not configured)
    """
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger


def parse_pdf_link_text(link_text: str) -> Optional[dict]:
    """
    Parse PDF/DOC link text to extract session info.

    Args:
        link_text: The link text containing session information

    Returns:
        Dictionary with parsed info or None if parsing fails
    """
    try:
        # 1. Date (Format: DD.MM.YYYY)
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', link_text)
        if not date_match:
            return None

        day = date_match.group(1).zfill(2)
        month = date_match.group(2).zfill(2)
        year = date_match.group(3)
        date_formatted = f"{year}-{month}-{day}"

        # 2. Session number (FIXED: Ignores -та, -ва, -ма suffixes)
        session_match = re.search(r'(\d{1,3})[^\d]*?седница', link_text, re.IGNORECASE)

        if not session_match:
            # Fallback: If written as "седница бр. 75"
            session_match = re.search(r'седница\s*(\d{1,3})', link_text, re.IGNORECASE)

        if not session_match:
            return None

        session_num = session_match.group(1).zfill(3)

        # 3. Continuation
        continuation = "00"
        if "продолжение" in link_text.lower():
            cont_match = re.search(r'(\d{1,2})[^\d]*?продолжение', link_text, re.IGNORECASE)
            continuation = cont_match.group(1).zfill(2) if cont_match else "01"

        # 4. Form clean filename - extension will be determined at download time
        filename = f"sednica_{session_num}_{continuation}_{date_formatted}.pdf"

        return {
            "session_num": session_num,
            "continuation": continuation,
            "date": date_formatted,
            "filename": filename,
            "original_text": link_text
        }
    except Exception:
        return None


def generate_fallback_filename(
        title: str,
        doc_id: str,
        url: str
) -> dict:
    """
    Generate a fallback filename when parsing fails.

    Args:
        title: Document title
        doc_id: Document ID
        url: Document URL

    Returns:
        Dictionary with filename info
    """
    ext = '.doc' if '.doc' in url.lower() else '.pdf'
    safe_title = re.sub(r'[^\w\-]', '_', title)[:50]

    return {
        'filename': f"stenogram_{doc_id}_{safe_title}{ext}",
        'original_text': title,
        'session_num': '000',
        'continuation': '00',
        'date': datetime.now().strftime('%Y-%m-%d')
    }