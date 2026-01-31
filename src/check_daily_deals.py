#!/usr/bin/env python3
"""
Check Amazon's daily Kindle deals and notify about matches.

Scrapes today's Kindle deals page, checks each against user's sample
library using similarity matching, sends email for matches.
"""

import argparse
import logging
import sys
import os
from typing import List, Dict, Any
from datetime import datetime

from config import Config
from database import Database
from similarity_matcher import SimilarityMatcher
from scraper import AmazonScraper
from email_notifier import EmailNotifier
from deal_logic import is_deal

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def scrape_daily_deals(page, config: Config) -> List[str]:
    """
    Scrape ASINs from Amazon's daily Kindle deals page.

    Args:
        page: Playwright page object
        config: Configuration object

    Returns:
        List of deal book ASINs
    """
    deals_url = "https://www.amazon.com/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D"

    logger.info(f"Navigating to daily deals page...")
    page.goto(deals_url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3000)

    asins = []

    # Find all product cards with ASINs
    # Amazon uses data-asin attribute on product cards
    products = page.locator('[data-asin]').all()

    logger.info(f"Found {len(products)} products on deals page")

    for product in products:
        try:
            asin = product.get_attribute('data-asin')
            if asin and len(asin) == 10:  # Valid ASIN format
                asins.append(asin)
        except Exception as e:
            logger.debug(f"Error extracting ASIN: {e}")
            continue

    # Remove duplicates
    unique_asins = list(set(asins))
    logger.info(f"Found {len(unique_asins)} unique deal ASINs")

    return unique_asins


def scrape_deal_book_info(page, asin: str) -> Dict[str, Any]:
    """
    Scrape book info from product page.

    Reuses similar logic to check_deals.py but simplified.

    Args:
        page: Playwright page object
        asin: Book ASIN

    Returns:
        Dict with title, author, current_price, list_price
    """
    import re

    url = f"https://www.amazon.com/dp/{asin}"
    logger.debug(f"Scraping {url}")

    try:
        page.goto(url, wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(2000)

        # Extract title
        title = None
        title_selectors = ['#productTitle', 'h1.a-spacing-none']
        for selector in title_selectors:
            elem = page.locator(selector).first
            if elem.count() > 0:
                title = elem.inner_text().strip()
                break

        # Extract author - try multiple selectors
        author = None
        author_selectors = [
            '.author .contributorNameID',
            '#bylineInfo .author a.contributorNameID',
            'span.author a',
            '#bylineInfo span.author'
        ]
        for selector in author_selectors:
            elem = page.locator(selector).first
            if elem.count() > 0:
                author = elem.inner_text().strip()
                break

        # Extract current price
        current_price = None
        price_selectors = [
            '.kindle-price .a-color-price',
            '#kindle-price',
            '.a-price .a-offscreen'
        ]
        for selector in price_selectors:
            elem = page.locator(selector).first
            if elem.count() > 0:
                price_text = elem.inner_text().strip()
                match = re.search(r'\$?(\d+\.\d{2})', price_text)
                if match:
                    current_price = float(match.group(1))
                    break

        # Extract list price
        list_price = None
        list_elem = page.locator('.a-text-price .a-offscreen').first
        if list_elem.count() > 0:
            price_text = list_elem.inner_text().strip()
            match = re.search(r'\$?(\d+\.\d{2})', price_text)
            if match:
                list_price = float(match.group(1))

        # Default list price to current price if not found
        if not list_price and current_price:
            list_price = current_price

        return {
            'title': title,
            'author': author,
            'current_price': current_price,
            'list_price': list_price
        }

    except Exception as e:
        logger.warning(f"Failed to scrape {asin}: {e}")
        return None


def check_daily_deals(config: Config, db: Database, dry_run: bool = False):
    """
    Check today's Kindle deals for matches.

    Args:
        config: Configuration object
        db: Database instance
        dry_run: If True, don't send emails or update database
    """
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000

    # Initialize matcher
    matcher = SimilarityMatcher(db)
    logger.info(f"Loaded matcher with {len(matcher.sample_authors)} authors, "
                f"{len(matcher.sample_series)} series, "
                f"{len(matcher.recommended_asins)} recommendations")

    matches = []

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Get daily deal ASINs
            deal_asins = scrape_daily_deals(page, config)

            logger.info(f"Checking {len(deal_asins)} deals for matches...")

            for asin in deal_asins:
                # Skip if already checked today
                if not dry_run and db.was_deal_checked_today(asin):
                    logger.debug(f"Skipping {asin} - already checked today")
                    continue

                # Scrape book info
                book_info = scrape_deal_book_info(page, asin)

                if not book_info or not book_info.get('title'):
                    logger.warning(f"Could not scrape info for {asin}")
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                title = book_info['title']
                author = book_info.get('author', '')
                current_price = book_info.get('current_price')
                list_price = book_info.get('list_price')

                # Check if it's a match
                is_match, match_reason = matcher.is_match(asin, author, title)

                if not is_match:
                    logger.debug(f"No match: {title}")
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                # Check if it's actually a deal
                if current_price is None or list_price is None:
                    logger.debug(f"Skipping {title} - no price info")
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                if not is_deal(current_price, list_price):
                    logger.info(f"Match but not a deal: {title} (${current_price})")
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                # It's a match AND a deal!
                logger.info(f"MATCH: {title} - {match_reason}")

                matches.append({
                    'asin': asin,
                    'title': title,
                    'author': author,
                    'current_price': current_price,
                    'list_price': list_price,
                    'match_reason': match_reason,
                    'cover_url': None  # Could scrape this too
                })

                if not dry_run:
                    db.add_deal_check(asin, was_deal=True, notified=True)

                # Rate limiting
                page.wait_for_timeout(3000)

            logger.info(f"Found {len(matches)} matching deals")

            # Send email if we have matches
            if matches and not dry_run:
                send_daily_deals_email(config, matches)
            elif matches and dry_run:
                logger.info("DRY RUN: Would send email with these matches:")
                for match in matches:
                    logger.info(f"  - {match['title']} ({match['match_reason']})")

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise


def send_daily_deals_email(config: Config, matches: List[Dict[str, Any]]):
    """
    Send email notification about daily deal matches.

    Args:
        config: Configuration object
        matches: List of matching deal books
    """
    smtp_server = config.get('email.smtp_server')
    smtp_port = config.get('email.smtp_port', 587)
    from_address = config.get('email.from_address')
    to_address = config.get('email.to_address')
    password = config.get_email_password()

    notifier = EmailNotifier(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        from_address=from_address,
        password=password
    )

    # Generate email HTML (will add match_reason support in next task)
    html_content = EmailNotifier.generate_email_html(matches)

    # Subject with count and date
    today = datetime.now().strftime('%Y-%m-%d')
    subject = f"Kindle Daily Deals - {len(matches)} matches - {today}"

    logger.info(f"Sending email to {to_address}...")
    notifier.send_email(
        to_address=to_address,
        subject=subject,
        html_content=html_content
    )
    logger.info("Email sent successfully!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Check Amazon daily Kindle deals for matches'
    )
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Check deals but don\'t send email or update database'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration
    try:
        config = Config(args.config)
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        sys.exit(1)

    # Connect to database
    try:
        db = Database(**config.get('database'))
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        sys.exit(1)

    # Check daily deals
    try:
        check_daily_deals(config, db, dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
