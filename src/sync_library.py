#!/usr/bin/env python3
"""
Sync Kindle library from Amazon My Books page.

This script logs into Amazon using Playwright, navigates to the My Books page,
and syncs your Kindle library (including samples) to the local database.
"""

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import List
from urllib.parse import quote

from config import Config
from database import Database
from scraper import AmazonScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


LIBRARY_CHECKBOX_SELECTOR = 'input[type="checkbox"][id*=":Kindle"]'


def wait_for_library(page, timeout_seconds: int = 300,
                     poll_interval: int = 3) -> int:
    """
    Poll until the library page shows books, or the timeout expires.

    Amazon intermittently bounces the digital console to /ap/signin with
    openid.pape.max_auth_age=3600, demanding a recent password entry; every weekly
    cron sync from 2026-08-23 to 2026-09-13 hit that page. Rather than block on a
    terminal keypress — impossible when the script is not driven from a TTY — watch
    the page itself and continue the moment the library renders, whether that is
    immediately or after the user signs in.

    Returns the number of book checkboxes found (0 if the timeout expired).
    """
    waited = 0
    while True:
        count = page.locator(LIBRARY_CHECKBOX_SELECTOR).count()
        if count > 0:
            return count
        if waited >= timeout_seconds:
            return 0
        page.wait_for_timeout(poll_interval * 1000)
        waited += poll_interval


def resolve_headless(config, headless_override: bool = None) -> bool:
    """
    Decide whether the library sync runs headless.

    Amazon's digital console refuses headless far more often than headed: every
    headless cron sync from 2026-08-23 to 2026-09-13 hit the password page, while
    headed runs went straight through. `sync.headless` therefore overrides the
    shared `scraping.headless` (which check_deals still uses headless, since the
    product pages it scrapes have no such problem).

    Precedence: explicit --headless flag, then sync.headless, then
    scraping.headless, then True.
    """
    if headless_override is not None:
        return headless_override

    sync_headless = config.get('sync.headless')
    if sync_headless is not None:
        return sync_headless

    return config.get('scraping.headless', True)


def scrape_recommendations(page, asin: str, domain: str = 'amazon.com',
                           scraper=None) -> List[str]:
    """
    Scrape 'Customers who bought this also bought' ASINs from product page.

    Args:
        page: Playwright page object
        asin: Book ASIN to scrape recommendations for
        domain: Amazon domain to use (e.g. 'amazon.com', 'amazon.co.uk')
        scraper: Optional AmazonScraper instance for session invalidation

    Returns:
        List of recommended ASINs
    """
    try:
        url = f"https://www.{domain}/dp/{asin}"
        logger.debug(f"Scraping recommendations from {url}")
        page.goto(url, wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(2000)

        # Check for session expiry or CAPTCHA
        if page.locator('input[name="email"]').count() > 0:
            logger.error(f"Hit login page scraping recommendations for {asin}")
            if scraper:
                scraper.mark_session_invalid()
            return []
        if page.locator('form[action*="captcha"]').count() > 0:
            logger.error(f"Hit CAPTCHA scraping recommendations for {asin}")
            if scraper:
                scraper.mark_session_invalid()
            return []

        recommendations = []

        # Try multiple selectors for recommendation carousels
        selectors = [
            '.similarities-widget a[href*="/dp/"]',
            '.p13n-desktop-carousel a[href*="/dp/"]',
            '[data-a-carousel-options] a[href*="/dp/"]',
            '.a-carousel-card a[href*="/dp/"]'
        ]

        for selector in selectors:
            links = page.locator(selector).all()
            if links:
                logger.debug(f"Found {len(links)} recommendation links with selector: {selector}")
                for link in links[:20]:  # Limit to 20 recommendations
                    try:
                        href = link.get_attribute('href')
                        if href and '/dp/' in href:
                            # Extract ASIN from URL like /dp/B01234ABCD/
                            match = re.search(r'/dp/([A-Z0-9]{10})', href)
                            if match:
                                rec_asin = match.group(1)
                                if rec_asin != asin:  # Don't recommend itself
                                    recommendations.append(rec_asin)
                    except Exception as e:
                        logger.debug(f"Error extracting ASIN from link: {e}")
                        continue

                if recommendations:
                    break  # Found recommendations, no need to try other selectors

        # Remove duplicates while preserving order
        seen = set()
        unique_recs = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recs.append(rec)

        logger.info(f"Found {len(unique_recs)} unique recommendations for {asin}")
        return unique_recs

    except Exception as e:
        logger.warning(f"Failed to scrape recommendations for {asin}: {e}")
        return []


def add_samples_to_collection(page, items: list, collection_name: str, dry_run: bool = False) -> int:
    """
    Add uncollected samples on the current page to a collection.

    Args:
        page: Playwright page object
        items: List of item dicts with 'asin', 'is_sample', 'collection_count'
        collection_name: Name of the collection to add to
        dry_run: If True, don't actually make changes

    Returns:
        Number of samples that would be/were added to collection
    """
    # Find samples with 0 collections
    uncollected = [item for item in items if item['is_sample'] and item['collection_count'] == 0]

    if not uncollected:
        return 0

    logger.info(f"Found {len(uncollected)} uncollected samples on this page")

    if dry_run:
        for item in uncollected:
            logger.info(f"  DRY RUN: Would add {item['asin']} to '{collection_name}'")
        return len(uncollected)

    try:
        # Check the checkbox for each uncollected sample
        for item in uncollected:
            # Checkbox id format: "{ASIN}:KindleEBookSample"
            checkbox = page.locator(f'input[id="{item["asin"]}:KindleEBookSample"]').first
            if checkbox.count() > 0 and not checkbox.is_checked():
                checkbox.check()
                logger.debug(f"Checked box for {item['asin']}")
            else:
                logger.warning(f"Could not find checkbox for {item['asin']}")

        page.wait_for_timeout(500)

        # Click "Add to Collections" button
        add_btn = page.locator('.action-button[aria-label="Add to Collections"]').first
        if add_btn.count() == 0:
            logger.warning("Could not find 'Add to Collections' button")
            return 0

        add_btn.click()
        page.wait_for_timeout(1000)

        # Find the collection checkbox in the bulk-add dialog
        # Checkboxes have ids like "BULK_ADD_TO_COLLECTION_DIALOG_ID_0"
        # Find the one next to a div containing the collection name
        collection_row = page.locator(f'div:has-text("{collection_name}")').locator('input[id^="BULK_ADD_TO_COLLECTION_DIALOG_ID_"]').first
        if collection_row.count() == 0:
            # Fallback: try finding the checkbox near the text
            collection_row = page.locator(f'input[id^="BULK_ADD_TO_COLLECTION_DIALOG_ID_"]').locator(f'xpath=ancestor::*[contains(.,"{collection_name}")]//input[starts-with(@id,"BULK_ADD_TO_COLLECTION_DIALOG_ID_")]').first
        if collection_row.count() == 0:
            logger.error(f"Collection '{collection_name}' not found in picker")
            try:
                page.keyboard.press('Escape')
            except Exception:
                pass
            return 0

        if not collection_row.is_checked():
            collection_row.check()
        page.wait_for_timeout(500)

        # Confirm the dialog
        confirm_btn = page.locator('#BULK_ADD_TO_COLLECTION_ACTION_ID_CONFIRM').first
        if confirm_btn.count() > 0:
            confirm_btn.click()
            page.wait_for_timeout(1000)

        logger.info(f"Added {len(uncollected)} samples to '{collection_name}'")
        return len(uncollected)

    except Exception as e:
        logger.warning(f"Failed to add samples to collection: {e}")
        try:
            page.keyboard.press('Escape')
        except Exception:
            pass
        return 0


def sync_library(config: Config, db: Database, dry_run: bool = False,
                 login_mode: bool = False, headless_override: bool = None,
                 force: bool = False, skip_collections: bool = False,
                 login_timeout: int = 600):
    """Sync Kindle library from Amazon My Books page"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    headless = resolve_headless(config, headless_override)

    page_timeout = config.get('scraping.page_timeout', 30) * 1000
    amazon_domain = config.get('amazon.domain', 'amazon.com')

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Navigate directly to library page — if session is valid, we'll get books
            logger.info("Navigating to Amazon All Books...")
            page.goto(f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc?pageNumber=1")
            page.wait_for_load_state('domcontentloaded')
            page.wait_for_timeout(2000)

            # Check if we got books or a login page
            book_divs_count = page.locator('input[type="checkbox"][id*=":Kindle"]').count()

            if book_divs_count == 0:
                # No books found — check if we hit a login page
                is_login_page = (page.locator('input[name="password"]').count() > 0
                                 or page.locator('h1:has-text("Sign")').count() > 0)

                if is_login_page and login_mode:
                    # Login mode: wait for the user to sign in in the browser window.
                    # No keypress required — we watch for the library to render, so
                    # this works even when the script is not attached to a terminal.
                    print("\n" + "=" * 70)
                    print("  Please log in to your Amazon account in the browser window")
                    print("=" * 70)
                    print("\nWaiting for the library to load (no keypress needed)...")
                    logger.info("Waiting up to %d minutes for Amazon login...",
                                login_timeout // 60)

                    book_divs_count = wait_for_library(page, timeout_seconds=login_timeout)

                    if book_divs_count == 0:
                        # Maybe signed in but left on another page — try the library once more.
                        logger.info("Re-checking library page...")
                        page.goto(f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc?pageNumber=1")
                        page.wait_for_load_state('domcontentloaded')
                        page.wait_for_timeout(2000)
                        book_divs_count = page.locator(LIBRARY_CHECKBOX_SELECTOR).count()

                    if book_divs_count == 0:
                        screenshot_path = os.path.expanduser("~/.kindle-deals/empty-page.png")
                        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                        page.screenshot(path=screenshot_path)
                        logger.error(f"Still no books found after login. Screenshot saved to {screenshot_path}")
                        sys.exit(2)
                elif is_login_page:
                    screenshot_path = os.path.expanduser("~/.kindle-deals/login-required.png")
                    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                    page.screenshot(path=screenshot_path)
                    logger.error(f"Not logged in to Amazon. Screenshot saved to {screenshot_path}")
                    logger.error("Please run with --login to log in and save your session.")
                    sys.exit(2)
                else:
                    screenshot_path = os.path.expanduser("~/.kindle-deals/empty-page.png")
                    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                    page.screenshot(path=screenshot_path)
                    logger.warning(f"No books found on page - screenshot saved to {screenshot_path}")
                    logger.warning("Your library may be empty or the page structure may have changed")

            if book_divs_count > 0:
                logger.info(f"Successfully loaded All Books page - found {book_divs_count} items")

            # Get total count from CONTENT_COUNT element
            total_items = 0
            total_pages = 1
            try:
                content_count = page.locator('#CONTENT_COUNT').first
                if content_count.count() > 0:
                    count_text = content_count.inner_text().strip()
                    # Parse "Showing 26 to 50 of 139 items" to extract 139
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

            # Early-stop tracking
            consecutive_known = 0
            early_stop_threshold = config.get('sync.early_stop_threshold', 10)
            should_stop = False
            all_items = []
            total_collections_added = 0

            # Scrape all pages
            for page_num in range(1, total_pages + 1):
                logger.info(f"Scraping page {page_num} of {total_pages}...")

                # Navigate to specific page
                if page_num > 1:
                    page.goto(f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc?pageNumber={page_num}")
                    page.wait_for_load_state('domcontentloaded')
                    page.wait_for_timeout(2000)

                # Find all item checkboxes — their id format is "{ASIN}:KindleEBook" or "{ASIN}:KindleEBookSample"
                # This gives us both the ASIN and sample/owned classification in one selector
                checkboxes = page.locator('input[type="checkbox"][id*=":Kindle"]').all()

                if not checkboxes:
                    logger.info(f"No books found on page {page_num}, stopping")
                    break

                logger.info(f"Found {len(checkboxes)} books on page {page_num}")

                page_items = []

                for checkbox in checkboxes:
                    try:
                        checkbox_id = checkbox.get_attribute('id')
                        if not checkbox_id or ':' not in checkbox_id:
                            logger.warning(f"Skipping checkbox without valid id: {checkbox_id}")
                            continue

                        # Parse "{ASIN}:KindleEBookSample" or "{ASIN}:KindleEBook"
                        asin, kind = checkbox_id.split(':', 1)
                        is_sample = 'Sample' in kind

                        # Detect collection count for samples
                        collection_count = 0
                        if is_sample:
                            try:
                                # Look for collection count text near this item's row
                                row = checkbox.locator('xpath=ancestor::div[contains(@class, "digital_entity")]').first
                                if row.count() > 0:
                                    coll_text = row.locator('text=/\\d+ Collection/').first
                                    if coll_text.count() > 0:
                                        text = coll_text.inner_text()
                                        match = re.search(r'(\d+)\s+Collection', text)
                                        if match:
                                            collection_count = int(match.group(1))
                            except Exception:
                                pass

                        page_items.append({
                            'asin': asin,
                            'is_sample': is_sample,
                            'collection_count': collection_count
                        })
                        logger.info(f"Found ASIN: {asin} ({'sample' if is_sample else 'owned'})")

                    except Exception as e:
                        logger.warning(f"Failed to extract ASIN: {e}")
                        continue

                all_items.extend(page_items)

                # Bulk lookup for early-stop tracking (one query per page instead of per-ASIN)
                page_asins = [item['asin'] for item in page_items]
                existing_on_page = db.get_existing_asins(page_asins)

                for item in page_items:
                    asin = item['asin']
                    existing = asin in existing_on_page
                    if existing:
                        consecutive_known += 1
                        if not force and consecutive_known >= early_stop_threshold and not should_stop:
                            logger.info(f"Early stop: {consecutive_known} consecutive known books found on page {page_num}")
                            should_stop = True
                    else:
                        consecutive_known = 0

                # TODO: Collection management disabled until selectors are validated against live page
                # if not skip_collections:
                #     try:
                #         collection_name = config.get('sync.collection_name', 'Read Me 2026')
                #         added = add_samples_to_collection(page, page_items, collection_name, dry_run)
                #         if added > 0:
                #             total_collections_added += added
                #     except Exception as e:
                #         logger.warning(f"Collection management error on page {page_num}: {e}")

                if should_stop:
                    logger.info("Stopping sync early (use --force for full sync)")
                    break

            logger.info(f"Total books found: {len(all_items)}")

            if dry_run:
                logger.info(f"DRY RUN: Would process {len(all_items)} books")
                if total_collections_added > 0:
                    logger.info(f"DRY RUN: Would add {total_collections_added} samples to collection")
                return

            # Add/update books in database.
            # Dual-state detection: an ASIN can appear twice on the library page —
            # once as KindleEBook (owned) and once as KindleEBookSample (sample).
            # We detect this two ways:
            #   1. Same ASIN appears twice in all_items (both states visible in this scan)
            #   2. The state we see now contradicts what's already in the DB
            #      (e.g. DB has is_sample=0 but library shows it as a sample, or vice versa)
            # In either case we keep is_sample=1 and set has_owned_copy=1.
            logger.info(f"Processing {len(all_items)} books...")
            added_count = 0
            skipped_count = 0
            dual_state_count = 0
            synced_asins = set()

            # First pass: collect which ASINs appear as both sample and owned in this scan
            asin_kinds: dict = defaultdict(set)
            for item in all_items:
                asin_kinds[item['asin']].add('sample' if item['is_sample'] else 'owned')
            dual_in_scan = {
                asin for asin, kinds in asin_kinds.items()
                if 'sample' in kinds and 'owned' in kinds
            }

            # Bulk pre-fetch known ASINs to avoid N+1 get_book queries
            all_asins_list = list({item['asin'] for item in all_items})
            known_asins_set = db.get_existing_asins(all_asins_list)

            seen_asins: set = set()
            for item in all_items:
                try:
                    asin = item['asin']
                    if asin in seen_asins:
                        # Second occurrence of same ASIN — dual state confirmed in this scan.
                        # has_owned_copy will already be set on the first pass below.
                        continue
                    seen_asins.add(asin)
                    synced_asins.add(asin)

                    is_sample_now = item['is_sample']
                    existing = db.get_book(asin) if asin in known_asins_set else None

                    # Determine if this is a dual-state book:
                    # - Appears as both sample and owned in the current scan, OR
                    # - DB says sample but library shows it as owned (or vice versa)
                    is_dual = asin in dual_in_scan
                    if existing and not is_dual:
                        db_is_sample = existing['is_sample'] == 1
                        if db_is_sample != is_sample_now:
                            # Contradicting states between DB and library → dual state
                            is_dual = True

                    if is_dual:
                        if not existing:
                            if not dry_run:
                                db.add_book(asin=asin, is_sample=True)
                            added_count += 1
                        else:
                            # Ensure is_sample=1 (may have been "upgraded" by old sync logic)
                            if existing['is_sample'] == 0 and not dry_run:
                                db.update_book_sample_status(asin, True)
                        if not dry_run:
                            db.set_has_owned_copy(asin, True)
                        logger.info(f"Dual state: {asin} is both sample and owned — marked for cleanup")
                        dual_state_count += 1
                    elif existing:
                        skipped_count += 1
                    else:
                        if not dry_run:
                            db.add_book(asin=asin, is_sample=is_sample_now)
                        added_count += 1

                except Exception as e:
                    logger.error(f"Failed to process ASIN {item['asin']}: {e}")

            logger.info(f"Added {added_count} new, {dual_state_count} dual-state flagged, {skipped_count} unchanged")

            # Report books eligible for sample cleanup
            if not dry_run:
                cleanup_books = db.get_samples_with_owned_copies()
                if cleanup_books:
                    logger.info(f"\n{'='*60}")
                    logger.info(f"SAMPLE CLEANUP: {len(cleanup_books)} book(s) have both a sample and owned copy.")
                    logger.info("You can delete the redundant sample using these URLs:")
                    for book in cleanup_books:
                        title = book.get('title')
                        if title:
                            encoded_title = quote(title, safe=':')
                            url = f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc/{encoded_title}"
                        else:
                            url = f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc"
                        display = title or book['asin']
                        logger.info(f"  {display}: {url}")
                    logger.info(f"{'='*60}\n")

            if total_collections_added > 0:
                logger.info(f"Collections: added {total_collections_added} samples to collection")

            # Only mark books as deleted during --force full syncs
            if force and not dry_run:
                all_sample_books = {book['asin'] for book in db.get_sample_books()}
                removed_asins = all_sample_books - synced_asins
                if removed_asins:
                    logger.info(f"Marking {len(removed_asins)} books as deleted (no longer in library)")
                    for asin in removed_asins:
                        db.mark_book_deleted(asin)
                        logger.debug(f"Marked {asin} as deleted")
                else:
                    logger.info("No books removed from library")
            elif not force:
                logger.info("Skipping removal check (early-stop mode, use --force for full sync)")

            # Scrape recommendations for samples
            logger.info("Scraping recommendations for samples...")
            asins_with_recs = db.get_asins_with_recommendations()
            all_rec_rows = []
            for item in all_items:
                asin = item['asin']

                # Only scrape recommendations for sample books
                if not item['is_sample']:
                    continue

                # Skip if we already have recommendations
                if asin in asins_with_recs:
                    logger.debug(f"Skipping {asin} - already has recommendations")
                    continue

                # Scrape recommendations
                recs = scrape_recommendations(page, asin, domain=amazon_domain, scraper=scraper)

                # Collect recommendation rows for bulk insert
                for rec_asin in recs:
                    all_rec_rows.append((asin, rec_asin))

                # Add delay to avoid rate limiting
                page.wait_for_timeout(3000)

            db.add_recommendations_bulk(all_rec_rows)
            logger.info(f"Stored {len(all_rec_rows)} recommendations")

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
    parser.add_argument('--login', action='store_true', help='Login mode')
    parser.add_argument('--login-timeout', type=int, default=600,
                        help='Seconds to wait for you to sign in during --login (default 600)')
    parser.add_argument('--force', action='store_true',
                        help='Force full sync — disable early stopping, enable removal tracking')
    parser.add_argument('--skip-collections', action='store_true',
                        help='Skip auto-adding uncollected samples to collection')
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

        headless_override = args.headless
        if args.login and headless_override is None:
            headless_override = False

        sync_library(config, db,
                     dry_run=args.dry_run,
                     login_mode=args.login,
                     headless_override=headless_override,
                     force=args.force,
                     skip_collections=args.skip_collections,
                     login_timeout=args.login_timeout)
        db.close()
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
