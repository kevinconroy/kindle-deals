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

            # Navigate to Amazon My Books
            logger.info("Navigating to Amazon My Books...")
            page.goto("https://www.amazon.com/hz/mycd/myx")

            # Wait for page to load
            page.wait_for_load_state('networkidle')

            # Check if logged in (look for sign-in elements)
            if page.locator('input[name="email"]').count() > 0:
                logger.error("Not logged in. Please run with --login to log in and save your session.")
                sys.exit(2)

            # Filter for samples using the dropdown
            logger.info("Filtering to view samples...")
            try:
                # Click the View dropdown and select "Samples"
                view_dropdown = page.locator('select#myx-content-type-filter')
                if view_dropdown.count() > 0:
                    view_dropdown.select_option('Sample')
                    page.wait_for_load_state('networkidle')
                    logger.info("Filtered to samples view")
                else:
                    logger.warning("Could not find view filter dropdown")
            except Exception as e:
                logger.warning(f"Could not filter to samples: {e}")

            # Scrape all pages
            samples = []
            page_num = 1

            while True:
                logger.info(f"Scraping page {page_num}...")

                # Find all book divs with class "digital_entity_title"
                book_divs = page.locator('.digital_entity_title').all()

                if not book_divs:
                    logger.info("No more books found")
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

                        # Extract title
                        title_element = div.locator('.a-size-base-plus').first
                        title = title_element.inner_text().strip() if title_element.count() > 0 else None

                        # Extract author
                        author_element = div.locator('.a-size-small.a-color-secondary').first
                        author = author_element.inner_text().strip() if author_element.count() > 0 else None

                        # Extract cover URL
                        cover_element = div.locator('img').first
                        cover_url = cover_element.get_attribute('src') if cover_element.count() > 0 else None

                        if not title:
                            logger.warning(f"Skipping book without title: {asin}")
                            continue

                        sample = {
                            'asin': asin,
                            'title': title,
                            'author': author,
                            'cover_url': cover_url
                        }
                        samples.append(sample)
                        logger.info(f"Found: {title} by {author} (ASIN: {asin})")

                    except Exception as e:
                        logger.warning(f"Failed to extract book data: {e}")
                        continue

                # Check for next page button
                next_button = page.locator('.a-pagination .a-last:not(.a-disabled)')
                if next_button.count() > 0:
                    logger.info("Moving to next page...")
                    next_button.click()
                    page.wait_for_load_state('networkidle')
                    page_num += 1
                else:
                    logger.info("No more pages")
                    break

            logger.info(f"Total books found: {len(samples)}")

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
