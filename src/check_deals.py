#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import time
from typing import List, Dict, Any

from config import Config
from database import Database
from scraper import AmazonScraper, extract_price, calculate_savings_percent
from deal_logic import should_notify
from email_notifier import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def scrape_book_price(page, asin: str, delay: float = 2.0) -> Dict[str, Any]:
    """Scrape price information for a book"""
    url = f"https://www.amazon.com/dp/{asin}"

    try:
        logger.debug(f"Scraping {url}")
        page.goto(url)
        page.wait_for_load_state('networkidle')

        # Extract Kindle price
        kindle_price_elem = page.locator('#kindle-price, .kindle-price').first
        kindle_price_text = kindle_price_elem.inner_text() if kindle_price_elem else None
        kindle_price = extract_price(kindle_price_text)

        # Extract list price
        list_price_elem = page.locator('.list-price, [data-a-strike="true"]').first
        list_price_text = list_price_elem.inner_text() if list_price_elem else None
        list_price = extract_price(list_price_text) or kindle_price

        time.sleep(delay)  # Rate limiting

        return {
            'kindle_price': kindle_price,
            'list_price': list_price
        }

    except Exception as e:
        logger.error(f"Failed to scrape price for {asin}: {e}")
        return {
            'kindle_price': None,
            'list_price': None
        }


def check_deals(config: Config, db: Database, target_asin: str = None):
    """Check for deals on tracked books"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000
    delay = config.get('scraping.delay_between_requests', 2)

    # Get books to check
    if target_asin:
        book = db.get_book(target_asin)
        books = [book] if book else []
    else:
        books = db.get_active_books()

    logger.info(f"Checking {len(books)} books for deals...")

    deals_found = []

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        for book in books:
            asin = book['asin']
            logger.info(f"Checking {book['title']}...")

            # Scrape current price
            price_data = scraper.retry_with_backoff(
                lambda: scrape_book_price(page, asin, delay)
            )

            current_price = price_data['kindle_price']
            list_price = price_data['list_price']

            # Save price history
            db.add_price_history(asin, current_price, list_price)

            if current_price is None or list_price is None:
                logger.warning(f"Could not determine price for {book['title']}")
                continue

            # Check if should notify
            last_notification = db.get_last_notification(asin)
            last_notified_price = last_notification['notified_price'] if last_notification else None

            if should_notify(current_price, list_price, last_notified_price):
                savings_percent = calculate_savings_percent(current_price, list_price)

                deal = {
                    'asin': asin,
                    'title': book['title'],
                    'author': book['author'],
                    'cover_url': book['cover_url'],
                    'current_price': current_price,
                    'list_price': list_price,
                    'savings_percent': savings_percent
                }
                deals_found.append(deal)

                # Record notification
                db.add_notification(asin, current_price)
                logger.info(f"Deal found: {book['title']} - ${current_price:.2f} ({savings_percent}% off)")

        page.close()

    # Send email if deals found
    if deals_found:
        logger.info(f"Sending email for {len(deals_found)} deals...")

        notifier = EmailNotifier(
            smtp_server=config.get('notifications.email.smtp_server'),
            smtp_port=config.get('notifications.email.smtp_port'),
            from_address=config.get('notifications.email.from_address'),
            password=config.get_email_password()
        )

        html = EmailNotifier.generate_email_html(deals_found)
        subject = f"Kindle Deals: {len(deals_found)} book(s) on sale!"
        to_address = config.get('notifications.email.to_address')

        notifier.send_email(to_address, subject, html)
        logger.info("Email sent successfully")
    else:
        logger.info("No deals found")


def main():
    parser = argparse.ArgumentParser(description='Check for Kindle deals')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--asin', help='Check specific ASIN')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config = Config(args.config)

        db = Database(
            host=config.get('database.host'),
            user=config.get('database.user'),
            password=config.get_mysql_password(),
            database=config.get('database.database')
        )
        check_deals(config, db, target_asin=args.asin)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
