#!/usr/bin/env python3
"""
Sync Kindle library from Amazon My Books page.

This script logs into Amazon using Playwright, navigates to the My Books page,
and syncs your Kindle library (including samples) to the local database.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from config import Config
from database import Database
from scraper import AmazonScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sync_library(config: Config, db: Database, dry_run: bool = False):
    """Sync Kindle library from Amazon My Books page"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Navigate to Amazon My Books
            logger.info("Navigating to Amazon My Books...")
            page.goto("https://www.amazon.com/hz/mycd/myx")

            # Wait for page to load
            page.wait_for_load_state('networkidle')

            # Check if logged in (look for sign-in elements)
            if page.locator('input[name="email"]').count() > 0:
                logger.error("Not logged in. Please run with --headless false and log in manually.")
                sys.exit(2)

            # Filter for samples
            logger.info("Syncing Kindle library...")
            # Note: Actual selectors would need to be determined by inspecting the page
            # This is a placeholder implementation

            samples = []
            sample_elements = page.locator('[data-content-type="Sample"]').all()

            logger.info(f"Found {len(sample_elements)} samples")

            for element in sample_elements:
                try:
                    title = element.locator('.title').inner_text()
                    author = element.locator('.author').inner_text()

                    # Extract ASIN from element attributes or links
                    asin = element.get_attribute('data-asin')

                    # Extract cover URL
                    cover_img = element.locator('img').first
                    cover_url = cover_img.get_attribute('src') if cover_img else None

                    sample = {
                        'asin': asin,
                        'title': title,
                        'author': author,
                        'cover_url': cover_url
                    }
                    samples.append(sample)
                    logger.info(f"Found: {title} by {author}")

                except Exception as e:
                    logger.warning(f"Failed to extract book data: {e}")
                    continue

            if dry_run:
                logger.info(f"DRY RUN: Would add {len(samples)} books to database")
                return

            # Add books to database
            for sample in samples:
                db.add_book(**sample)
                logger.info(f"Added to database: {sample['title']}")

            logger.info(f"Successfully synced {len(samples)} books")

        except Exception as e:
            logger.error(f"Failed to sync library: {e}")
            raise
        finally:
            page.close()


def main():
    parser = argparse.ArgumentParser(description='Sync Kindle library from Amazon')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config = Config(args.config)

        db = Database(
            host=config.get('database.host'),
            user=config.get('database.user'),
            password=config.get('database.password'),
            database=config.get('database.database')
        )
        sync_library(config, db, dry_run=args.dry_run)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
