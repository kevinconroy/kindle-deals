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


def sync_library(config: Config, db: Database, dry_run: bool = False, login_mode: bool = False, headless_override: bool = None):
    """Sync Kindle library from Amazon My Books page"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    # Use override if provided, otherwise use config
    if headless_override is not None:
        headless = headless_override
    else:
        headless = config.get('scraping.headless', True)

    page_timeout = config.get('scraping.page_timeout', 30) * 1000

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Login mode: Let user log in before scraping
            if login_mode:
                logger.info("Opening Amazon for login...")
                page.goto("https://www.amazon.com")
                page.wait_for_load_state('networkidle')

                print("\n" + "=" * 70)
                print("  Please log in to your Amazon account in the browser window")
                print("=" * 70)
                print("\nOnce you're logged in, press Enter to continue...")
                input()

                logger.info("Login complete, saving session...")

            # Navigate directly to Books & Samples page
            logger.info("Navigating to Amazon Books & Samples...")
            page.goto("https://www.amazon.com/hz/mycd/digital-console/contentlist/booksSamples/dateDsc?pageNumber=1")

            # Wait for page to load
            page.wait_for_load_state('networkidle')

            # Check if logged in (look for sign-in elements)
            if page.locator('input[name="email"]').count() > 0:
                logger.error("Not logged in. Please run with --login to log in and save your session.")
                sys.exit(2)

            # Get total count from CONTENT_COUNT element
            total_items = 0
            total_pages = 1
            try:
                content_count = page.locator('#CONTENT_COUNT').first
                if content_count.count() > 0:
                    count_text = content_count.inner_text().strip()
                    # Parse "Showing 26 to 50 of 139 items" to extract 139
                    import re
                    match = re.search(r'of (\d+) items?', count_text)
                    if match:
                        total_items = int(match.group(1))
                        total_pages = (total_items + 24) // 25  # Round up
                        logger.info(f"Found {total_items} total items, will scrape {total_pages} pages")
                    else:
                        logger.warning(f"Could not parse count from: {count_text}")
            except Exception as e:
                logger.warning(f"Could not determine total count: {e}")
                logger.info("Will scrape until error...")

            # Scrape all pages
            samples = []

            for page_num in range(1, total_pages + 1):
                logger.info(f"Scraping page {page_num} of {total_pages}...")

                # Navigate to specific page
                if page_num > 1:
                    page.goto(f"https://www.amazon.com/hz/mycd/digital-console/contentlist/booksSamples/dateDsc?pageNumber={page_num}")
                    page.wait_for_load_state('networkidle')

                # Find all book divs with class "digital_entity_title"
                book_divs = page.locator('.digital_entity_title').all()

                if not book_divs:
                    logger.info(f"No books found on page {page_num}, stopping")
                    break

                logger.info(f"Found {len(book_divs)} books on page {page_num}")

                for div in book_divs:
                    try:
                        # Extract ASIN from div id (format: "content-title-B076NTR2WX")
                        div_id = div.get_attribute('id')
                        if not div_id or not div_id.startswith('content-title-'):
                            logger.warning(f"Skipping div without valid id: {div_id}")
                            continue

                        asin = div_id.replace('content-title-', '')

                        # Store just the ASIN - title/author will be fetched via API later
                        samples.append({'asin': asin})
                        logger.info(f"Found ASIN: {asin}")

                    except Exception as e:
                        logger.warning(f"Failed to extract ASIN: {e}")
                        continue

            logger.info(f"Total books found: {len(samples)}")

            if dry_run:
                logger.info(f"DRY RUN: Would add {len(samples)} books to database")
                return

            # Add books to database
            logger.info(f"Adding {len(samples)} books to database...")
            added_count = 0
            skipped_count = 0
            for sample in samples:
                try:
                    was_added = db.add_book(**sample)
                    if was_added:
                        added_count += 1
                        logger.debug(f"Added ASIN {sample['asin']} to database")
                    else:
                        skipped_count += 1
                        logger.debug(f"Skipped ASIN {sample['asin']} (already exists)")
                except Exception as e:
                    logger.error(f"Failed to add ASIN {sample['asin']} to database: {e}")

            logger.info(f"Successfully added {added_count} new books, {skipped_count} already existed")

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
    parser.add_argument('--login', action='store_true', help='Login mode - opens browser and waits for you to log in')
    parser.add_argument('--headless', type=lambda x: x.lower() == 'true', default=None,
                        help='Override headless mode (true/false)')

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

        # If login mode, force non-headless
        headless_override = args.headless
        if args.login and headless_override is None:
            headless_override = False

        sync_library(config, db, dry_run=args.dry_run, login_mode=args.login, headless_override=headless_override)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
