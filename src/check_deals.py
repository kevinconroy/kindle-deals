#!/usr/bin/env python3
import argparse
import logging
import sys
from typing import List, Dict, Any

from config import Config
from database import Database
from paapi5_python_sdk.api.default_api import DefaultApi
from paapi5_python_sdk.partner_type import PartnerType
from paapi5_python_sdk.rest import ApiException
from paapi5_python_sdk.get_items_request import GetItemsRequest
from paapi5_python_sdk.get_items_resource import GetItemsResource
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
    access_key = config.get('amazon.api_access_key')
    secret_key = config.get('amazon.api_secret_key')
    associate_tag = config.get('amazon.api_associate_tag')
    region = config.get('amazon.api_region', 'US')

    # Map region to host and marketplace
    region_mapping = {
        'US': ('webservices.amazon.com', 'www.amazon.com'),
        'UK': ('webservices.amazon.co.uk', 'www.amazon.co.uk'),
        'FR': ('webservices.amazon.fr', 'www.amazon.fr'),
        'DE': ('webservices.amazon.de', 'www.amazon.de'),
        'JP': ('webservices.amazon.co.jp', 'www.amazon.co.jp'),
        'CA': ('webservices.amazon.ca', 'www.amazon.ca'),
    }
    host, marketplace = region_mapping.get(region, ('webservices.amazon.com', 'www.amazon.com'))

    api = DefaultApi(
        access_key=access_key,
        secret_key=secret_key,
        host=host,
        region=region
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
        title = book['title'] or asin
        logger.info(f"Checking {title}...")

        try:
            # Create GetItems request
            get_items_request = GetItemsRequest(
                partner_tag=associate_tag,
                partner_type=PartnerType.ASSOCIATES,
                marketplace=marketplace,
                item_ids=[asin],
                resources=[
                    GetItemsResource.ITEMINFO_TITLE,
                    GetItemsResource.ITEMINFO_BYLINEINFO,
                    GetItemsResource.IMAGES_PRIMARY_LARGE,
                    GetItemsResource.OFFERS_LISTINGS_PRICE,
                    GetItemsResource.OFFERS_LISTINGS_SAVINGBASIS,
                ]
            )

            # Get item info from API
            response = api.get_items(get_items_request)

            current_price = None
            list_price = None
            author = book['author']
            cover_url = book['cover_url']

            if response.items_result and response.items_result.items:
                item = response.items_result.items[0]

                # Update metadata if book title is missing
                if not book['title']:
                    # Extract title
                    if item.item_info and item.item_info.title and item.item_info.title.display_value:
                        title = item.item_info.title.display_value
                        logger.info(f"Updated title from API: {title}")

                    # Extract author
                    if item.item_info and item.item_info.by_line_info and item.item_info.by_line_info.contributors:
                        contributors = item.item_info.by_line_info.contributors
                        if contributors and len(contributors) > 0:
                            author = contributors[0].name
                            logger.info(f"Updated author from API: {author}")

                    # Extract cover URL
                    if item.images and item.images.primary and item.images.primary.large:
                        cover_url = item.images.primary.large.url
                        logger.info(f"Updated cover URL from API")

                    # Update database with metadata
                    db.update_book_metadata(asin, title, author, cover_url)

                # Extract Kindle price from offers
                if item.offers and item.offers.listings:
                    listing = item.offers.listings[0]
                    current_price = listing.price.amount if listing.price else None
                    list_price = listing.saving_basis.amount if listing.saving_basis else current_price

        except ApiException as e:
            logger.error(f"API error for {asin}: {e}")
            continue
        except Exception as e:
            logger.error(f"Failed to process {asin}: {e}")
            continue

        # Save price history
        db.add_price_history(asin, current_price, list_price)

        if current_price is None or list_price is None:
            logger.warning(f"Could not determine price for {title}")
            continue

        # Check if should notify
        last_notification = db.get_last_notification(asin)
        last_notified_price = last_notification['notified_price'] if last_notification else None

        if should_notify(current_price, list_price, last_notified_price):
            savings_percent = calculate_savings_percent(current_price, list_price)

            deal = {
                'asin': asin,
                'title': title,
                'author': author,
                'cover_url': cover_url,
                'current_price': current_price,
                'list_price': list_price,
                'savings_percent': savings_percent
            }
            deals_found.append(deal)

            # Record notification
            db.add_notification(asin, current_price)
            logger.info(f"Deal found: {title} - ${current_price:.2f} ({savings_percent}% off)")

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
