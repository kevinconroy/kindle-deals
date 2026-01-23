#!/usr/bin/env python3
import argparse
import logging
import sys
from typing import List, Dict, Any

from config import Config
from database import Database
from amazon.paapi import AmazonAPI
from deal_logic import should_notify
from email_notifier import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_savings_percent(current_price: float, list_price: float) -> int:
    """Calculate savings percentage"""
    if list_price == 0:
        return 0

    savings = ((list_price - current_price) / list_price) * 100
    return int(round(savings))


def check_deals(config: Config, db: Database, target_asin: str = None):
    """Check for deals on tracked books using Amazon Product Advertising API"""
    # Initialize Amazon API
    api = AmazonAPI(
        access_key=config.get('amazon.api_access_key'),
        secret_key=config.get('amazon.api_secret_key'),
        associate_tag=config.get('amazon.api_associate_tag'),
        region=config.get('amazon.api_region', 'US')
    )

    # Get books to check
    if target_asin:
        book = db.get_book(target_asin)
        books = [book] if book else []
    else:
        books = db.get_active_books()

    logger.info(f"Checking {len(books)} books for deals...")

    deals_found = []

    for book in books:
        asin = book['asin']
        logger.info(f"Checking {book['title']}...")

        try:
            # Get item info from API
            items = api.get_items(
                [asin],
                item_ids_type='ASIN',
                resources=['Offers.Listings.Price', 'Offers.Listings.SavingBasis']
            )

            current_price = None
            list_price = None

            if items and items[0]:
                item = items[0]
                # Extract Kindle price from offers
                if item.offers and item.offers.listings:
                    listing = item.offers.listings[0]
                    current_price = listing.price.amount if listing.price else None
                    list_price = listing.saving_basis.amount if listing.saving_basis else current_price

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

        except Exception as e:
            logger.error(f"Failed to get price for {asin}: {e}")
            continue

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
            password=config.get('database.password'),
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
