"""
Configuration classes for Sobranie Bot.
"""

from pathlib import Path

# Project root directory (where main.py is located)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class BotConfig:
    """Central configuration for the bot."""
    BASE_URL = "https://www.sobranie.mk"
    SESSIONS_URL = "https://www.sobranie.mk/plenarni-sednici-parlament.nspx"

    # API endpoint for sessions (discovered from the Angular app)
    SESSIONS_API_URL = "https://api.sobranie.mk"

    # Use absolute paths based on project root
    DATA_DIR = PROJECT_ROOT / "data"
    RAW_DIR = DATA_DIR / "raw"
    PROCESSED_DIR = DATA_DIR / "processed"
    HISTORY_FILE = DATA_DIR / "history.json"
    LOG_FILE = PROJECT_ROOT / "sobranie_bot.log"

    REQUEST_TIMEOUT = 60
    REQUEST_DELAY = 1.0
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Pagination settings
    MAX_PAGES_TO_SCRAPE = 10  # Maximum pages to scrape (safety limit)


class ParserConfig:
    """Parser configuration."""
    GUTTER_SEARCH_START = 0.40
    GUTTER_SEARCH_END = 0.60
    MIN_GUTTER_WIDTH = 8.0
    DENSITY_THRESHOLD = 2
    FALLBACK_GUTTER_RATIO = 0.50
    MIN_SPEECH_LENGTH = 3
    Y_TOLERANCE = 4.0
    DENSITY_MAP_RESOLUTION = 1.0
    COLUMN_MARGIN = 5.0
    FOOTER_ZONE_RATIO = 0.05