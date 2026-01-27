#!/usr/bin/env python3
"""
Sobranie Bot - Automated Parliament Session Crawler & Parser
=============================================================

Main entry point for the bot.

Author: Senior Data Engineering Team
Version: 2.0 (Refactored)
License: MIT
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

import schedule

from src.config import BotConfig
from src.utils import setup_logger
from src.storage import HistoryManager
from src.crawler import SobranieCrawler
from src.parser import SobranieParser


class SobranieBot:
    """Main bot that orchestrates crawling, downloading, and parsing."""

    def __init__(self):
        """Initialize the bot with all components."""
        self.config = BotConfig()

        # Initialize logger with file output
        self.logger = setup_logger(
            log_file=str(self.config.LOG_FILE)
        )

        self.crawler = SobranieCrawler(self.config)
        self.parser = SobranieParser()
        self.history = HistoryManager(self.config.HISTORY_FILE)

        # Ensure directories exist
        self.config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        self.config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    def process_session(self, session: dict) -> bool:
        """
        Process a single session: download ALL matching PDFs and parse them.

        Args:
            session: Session dictionary with sitting_id and details_url

        Returns:
            True if at least one file was processed successfully
        """
        sitting_id = session["sitting_id"]
        details_url = session["details_url"]

        self.logger.info(f"Processing session: {sitting_id}")

        # Get list of stenograph documents
        found_files = self.crawler.get_stenograph_pdf_urls(details_url)

        if not found_files:
            self.logger.warning(f"No PDFs found for session {sitting_id}")
            return False

        success_count = 0

        for pdf_url, pdf_info in found_files:
            self.logger.info(f"  Found document: {pdf_info['filename']}")

            # Determine initial output path
            pdf_path = self.config.RAW_DIR / pdf_info["filename"]

            # Download the file
            download_success, actual_path = self.crawler.download_pdf(pdf_url, pdf_path)

            if not download_success or actual_path is None:
                self.logger.error(f"Failed to download {pdf_info['filename']}")
                continue

            # Only parse PDF files
            if actual_path.suffix.lower() != '.pdf':
                self.logger.warning(f"Skipping non-PDF file: {actual_path.name}")
                continue

            # Create JSONL output path based on actual filename
            jsonl_filename = actual_path.stem + ".jsonl"
            jsonl_path = self.config.PROCESSED_DIR / jsonl_filename

            try:
                speech_count = self.parser.parse_to_jsonl(actual_path, jsonl_path)
                self.logger.info(f"  ✓ Parsed {speech_count} speeches from {actual_path.name}")
                success_count += 1

            except Exception as e:
                self.logger.error(f"Failed to parse {actual_path.name}: {e}")

        if success_count > 0:
            # Mark the session as processed in history
            self.history.mark_processed(sitting_id, {
                "files_processed": success_count,
                "total_files_found": len(found_files),
                "last_processed": datetime.now().isoformat()
            })
            self.logger.info(f"✓ Session {sitting_id} complete. Processed {success_count} files.")
            return True
        else:
            return False

    def run(self) -> dict:
        """
        Run the bot: crawl, download, and parse new sessions.

        Returns:
            Dictionary with run statistics
        """
        self.logger.info("=" * 70)
        self.logger.info("SOBRANIE BOT - Starting run")
        self.logger.info(f"Time: {datetime.now().isoformat()}")
        self.logger.info("=" * 70)

        stats = {
            "started_at": datetime.now().isoformat(),
            "sessions_found": 0,
            "sessions_new": 0,
            "sessions_processed": 0,
            "sessions_failed": 0
        }

        # Get finished sessions
        sessions = self.crawler.get_finished_sessions()
        stats["sessions_found"] = len(sessions)

        # Process new sessions
        for session in sessions:
            sitting_id = session["sitting_id"]

            # Skip if already processed
            if self.history.is_processed(sitting_id):
                self.logger.debug(f"Skipping already processed: {sitting_id}")
                continue

            stats["sessions_new"] += 1

            if self.process_session(session):
                stats["sessions_processed"] += 1
            else:
                stats["sessions_failed"] += 1

        stats["finished_at"] = datetime.now().isoformat()

        self.logger.info("=" * 70)
        self.logger.info("SOBRANIE BOT - Run complete")
        self.logger.info(f"Sessions found: {stats['sessions_found']}")
        self.logger.info(f"New sessions: {stats['sessions_new']}")
        self.logger.info(f"Successfully processed: {stats['sessions_processed']}")
        self.logger.info(f"Failed: {stats['sessions_failed']}")
        self.logger.info("=" * 70)

        return stats


def job():
    """The scheduled job function."""
    logger = setup_logger()
    logger.info("Scheduled job triggered")
    try:
        bot = SobranieBot()
        bot.run()
    except Exception as e:
        logger.error(f"Job failed with error: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sobranie Bot - Automated Parliament Session Crawler & Parser"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't schedule)"
    )
    parser.add_argument(
        "--schedule-day",
        default="friday",
        help="Day to run scheduled job (default: friday)"
    )
    parser.add_argument(
        "--schedule-time",
        default="18:00",
        help="Time to run scheduled job (default: 18:00)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Setup logger
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logger(
        log_file=str(BotConfig.LOG_FILE),
        level=log_level
    )

    # Run immediately once
    logger.info("Running initial job...")
    job()

    if args.once:
        logger.info("--once flag set, exiting after single run")
        return

    # Schedule recurring job
    schedule_func = getattr(schedule.every(), args.schedule_day)
    schedule_func.at(args.schedule_time).do(job)

    logger.info(f"Scheduled to run every {args.schedule_day} at {args.schedule_time}")
    logger.info("Bot is running. Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")


if __name__ == "__main__":
    main()