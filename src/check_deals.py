#!/usr/bin/env python3
import argparse
import logging
import sys
import os
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from config import Config
from database import Database
from scraper import AmazonScraper
from deal_logic import should_notify, is_deal
from similarity_matcher import SimilarityMatcher
from email_notifier import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_current_deal_day() -> datetime:
    """
    Get the current "deal day" considering 3 AM Eastern reset time.

    Deals reset at 3 AM Eastern, so before 3 AM counts as previous day.
    Returns midnight of the current deal day.
    """
    from datetime import timezone

    # Get current UTC time
    now_utc = datetime.now(timezone.utc)

    # Convert to Eastern Time (UTC-5, or UTC-4 during DST)
    # Simple approximation: use UTC-5 (we can adjust if needed)
    eastern_offset = timedelta(hours=-5)
    now_eastern = now_utc + eastern_offset

    # If before 3 AM, use previous day
    if now_eastern.hour < 3:
        deal_day = now_eastern.date() - timedelta(days=1)
    else:
        deal_day = now_eastern.date()

    # Return as datetime at midnight
    return datetime.combine(deal_day, datetime.min.time())


def calculate_savings_percent(current_price: float, list_price: float) -> int:
    """Calculate savings percentage"""
    if list_price == 0:
        return 0

    savings = ((list_price - current_price) / list_price) * 100
    return int(round(savings))


def scrape_book_info(page, asin: str) -> Optional[Dict[str, Any]]:
    """Scrape book information from Amazon product page"""
    try:
        # Navigate to product page
        url = f"https://www.amazon.com/dp/{asin}"
        logger.debug(f"Navigating to {url}")
        page.goto(url, wait_until='domcontentloaded', timeout=15000)

        # Wait a bit for dynamic content, but don't wait for networkidle (can hang)
        page.wait_for_timeout(2000)

        # Check if we hit a CAPTCHA or login page
        if page.locator('input[name="email"]').count() > 0:
            logger.error(f"Hit login page for {asin} - session may have expired")
            return None

        if page.locator('form[action*="captcha"]').count() > 0:
            logger.error(f"Hit CAPTCHA for {asin} - may need to slow down")
            return None

        # Check if book is already owned (has "Read Now" button)
        # Note: "Read for Free" just means Kindle Unlimited, NOT owned
        already_owned = False
        read_now_selectors = [
            ('button:has-text("Read Now")', 'button with text Read Now'),
            ('a:has-text("Read Now")', 'link with text Read Now'),
            ('#kindle-reader-button', 'kindle reader button'),
            ('a[href*="/read/"]', 'read link'),
            ('input[value*="Read Now"]', 'input with Read Now'),
            ('#kop-button-ingress', 'Kindle Owners Program button')
        ]
        for selector, description in read_now_selectors:
            try:
                count = page.locator(selector).count()
                if count > 0:
                    logger.info(f"Book {asin} already owned (found {description})")
                    already_owned = True
                    break
            except Exception as e:
                logger.debug(f"Error checking selector {selector}: {e}")
                continue

        if already_owned:
            return {
                'title': None,
                'author': None,
                'cover_url': None,
                'current_price': None,
                'list_price': None,
                'already_owned': True
            }
        else:
            # Check for "Buy now" button to confirm it's not owned
            buy_now_count = page.locator('input[value*="Buy now"], button:has-text("Buy now")').count()
            if buy_now_count > 0:
                logger.debug(f"Book {asin} not owned (found 'Buy now' button)")
            else:
                logger.debug(f"Book {asin} not owned (no 'Read Now' button found)")

        # Extract title
        title = None
        try:
            title_elem = page.locator('#productTitle').first
            title_elem.wait_for(state='visible', timeout=3000)
            title = title_elem.inner_text().strip()
            logger.debug(f"Found title: {title}")
        except Exception as e:
            logger.debug(f"Could not find title: {e}")
            pass

        # Extract author - try multiple selectors
        author = None
        author_selectors = [
            '.author .contributorNameID',
            '#bylineInfo .author a.contributorNameID',
            'span.author a',
            '#bylineInfo span.author',
            'a[data-asin] .author',
            '.contributorNameTrigger'
        ]
        for selector in author_selectors:
            try:
                author_elem = page.locator(selector).first
                if author_elem.count() > 0:
                    author = author_elem.inner_text().strip()
                    logger.debug(f"Found author: {author} using selector: {selector}")
                    break
            except Exception:
                continue
        if not author:
            logger.debug(f"Could not find author for {asin}")

        # Extract cover image - try multiple selectors
        cover_url = None
        cover_selectors = [
            '#ebooksImgBlkFront',
            '#imgBlkFront',
            '#ebooksProductImage',
            '#landingImage',
            'img.a-dynamic-image',
            '#main-image',
            'img[data-a-dynamic-image]'
        ]
        for selector in cover_selectors:
            try:
                img_elem = page.locator(selector).first
                if img_elem.count() > 0:
                    cover_url = img_elem.get_attribute('src')
                    logger.debug(f"Found cover: {cover_url} using selector: {selector}")
                    break
            except Exception:
                continue
        if not cover_url:
            logger.debug(f"Could not find cover for {asin}")

        # Extract Kindle price
        current_price = None
        try:
            # Try multiple selectors for Kindle price
            price_selectors = [
                'span.a-price .a-offscreen',
                '.kindle-price .a-color-price',
                '#kindle-price',
                '#price',
                '.a-price .a-offscreen'
            ]
            for selector in price_selectors:
                try:
                    price_elem = page.locator(selector).first
                    if price_elem.count() > 0:
                        price_text = price_elem.inner_text().strip()
                        # Extract number from price text (e.g., "$3.99" -> 3.99)
                        match = re.search(r'\$?(\d+\.\d{2})', price_text)
                        if match:
                            current_price = float(match.group(1))
                            logger.debug(f"Found current price: ${current_price} using {selector}")
                            break
                except Exception:
                    continue

            if not current_price:
                logger.debug(f"Could not find current price for {asin}")
        except Exception as e:
            logger.debug(f"Error extracting current price: {e}")
            pass

        # Extract list price (original price)
        list_price = None
        try:
            list_price_elem = page.locator('.a-text-price .a-offscreen').first
            if list_price_elem.count() > 0:
                price_text = list_price_elem.inner_text().strip()
                match = re.search(r'\$?(\d+\.\d{2})', price_text)
                if match:
                    list_price = float(match.group(1))
                    logger.debug(f"Found list price: ${list_price}")
        except Exception as e:
            logger.debug(f"Error extracting list price: {e}")
            pass

        # If no list price, use current price
        if not list_price and current_price:
            list_price = current_price

        return {
            'title': title,
            'author': author,
            'cover_url': cover_url,
            'current_price': current_price,
            'list_price': list_price
        }

    except Exception as e:
        logger.error(f"Failed to scrape {asin}: {e}")
        return None


def scrape_daily_deals(page) -> List[str]:
    """Scrape ASINs from Amazon's daily Kindle deals page."""
    deals_url = "https://www.amazon.com/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D"

    logger.info("Navigating to daily deals page...")
    page.goto(deals_url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3000)

    asins = []
    products = page.locator('[data-asin]').all()
    logger.info(f"Found {len(products)} products on deals page")

    for product in products:
        try:
            asin = product.get_attribute('data-asin')
            if asin and len(asin) == 10:
                asins.append(asin)
        except Exception as e:
            logger.debug(f"Error extracting ASIN: {e}")
            continue

    unique_asins = list(set(asins))
    logger.info(f"Found {len(unique_asins)} unique deal ASINs")
    return unique_asins


def check_daily_deals_phase(page, db: Database, check_delay: int, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Check today's daily deals for matches against user's interests.

    Returns list of deal dicts for matched books.
    """
    matcher = SimilarityMatcher(db)
    logger.info(f"Loaded matcher with {len(matcher.sample_authors)} authors, "
                f"{len(matcher.sample_series)} series, "
                f"{len(matcher.recommended_asins)} recommendations")

    deals_found = []
    deal_asins = scrape_daily_deals(page)
    logger.info(f"Checking {len(deal_asins)} daily deals for matches...")

    for asin in deal_asins:
        # Skip if already checked today
        if not dry_run and db.was_deal_checked_today(asin):
            logger.debug(f"Skipping {asin} - already checked today")
            continue

        # Scrape book info using the full scraper
        book_info = scrape_book_info(page, asin)

        if not book_info or book_info.get('already_owned'):
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        title = book_info.get('title')
        author = book_info.get('author', '')
        current_price = book_info.get('current_price')
        list_price = book_info.get('list_price')

        if not title:
            logger.warning(f"Could not scrape info for {asin}")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        # Check if it matches user's interests
        is_match, match_reason = matcher.is_match(asin, author, title)

        if not is_match:
            logger.debug(f"No match: {title}")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        # Check price
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

        savings_percent = calculate_savings_percent(current_price, list_price)
        previous_price = db.get_previous_price(asin) if db.get_book(asin) else None
        logger.info(f"Daily deal match: {title} - ${current_price:.2f} ({match_reason})")

        deals_found.append({
            'asin': asin,
            'title': title,
            'author': author,
            'cover_url': book_info.get('cover_url'),
            'current_price': current_price,
            'list_price': list_price,
            'previous_price': previous_price,
            'savings_percent': savings_percent,
            'match_reason': match_reason
        })

        if not dry_run:
            db.add_deal_check(asin, was_deal=True, notified=True)

        time.sleep(check_delay / 1000)

    logger.info(f"Found {len(deals_found)} daily deal matches")
    return deals_found


def check_deals(config: Config, db: Database, target_asin: str = None, force: bool = False, dry_run: bool = False, skip_samples: bool = False, skip_daily: bool = False):
    """
    Check for deals on tracked books and daily deals page.

    Args:
        config: Configuration object
        db: Database instance
        target_asin: Optional specific ASIN to check
        force: Force check even if already checked today
        dry_run: If True, don't send emails or update database
        skip_samples: If True, skip checking sample book prices
        skip_daily: If True, skip checking daily deals page
    """
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000
    check_delay = config.get('scraping.check_delay', 2000)

    # Get current deal day (considers 3 AM Eastern reset)
    deal_day = get_current_deal_day()
    logger.info(f"Deal day: {deal_day.date()} (deals reset at 3 AM Eastern)")

    deals_found = []

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Phase 1: Check sample book prices
            if not skip_samples:
                # Get books to check
                if target_asin:
                    book = db.get_book(target_asin)
                    if book and (book['is_sample'] == 0 or book['is_deleted'] == 1):
                        logger.warning(f"Book {target_asin} is not a sample or is deleted - skipping")
                        books = []
                    else:
                        books = [book] if book else []
                else:
                    books = db.get_sample_books()
                    logger.debug(f"Fetched {len(books)} books from get_sample_books()")

                # Filter out inactive books and books already checked today (unless force flag is set)
                books_to_check = []
                skipped_count = 0
                inactive_count = 0

                for book in books:
                    # Double-check that book is actually active (safety check)
                    if book['is_sample'] == 0 or book['is_deleted'] == 1:
                        logger.debug(f"Skipping {book['title'] or book['asin']} (not sample or deleted)")
                        inactive_count += 1
                        continue

                    # Skip books already checked today (unless force flag)
                    if not force and db.was_checked_today(book['asin'], deal_day):
                        logger.debug(f"Skipping {book['title'] or book['asin']} (already checked today)")
                        skipped_count += 1
                        continue

                    books_to_check.append(book)

                books = books_to_check

                if inactive_count > 0:
                    logger.warning(f"Filtered out {inactive_count} inactive books (these should not have been in the active books list)")
                if skipped_count > 0:
                    logger.info(f"Skipped {skipped_count} books already checked today (use --force to override)")

                logger.info(f"Checking {len(books)} active books for deals...")

                for book in books:
                    asin = book['asin']
                    title = book['title'] or asin
                    url = f"https://www.amazon.com/dp/{asin}"
                    logger.info(f"Checking {title}... ({url})")

                    try:
                        # Scrape book information
                        book_info = scrape_book_info(page, asin)

                        if not book_info:
                            logger.warning(f"Could not scrape info for {asin}")
                            continue

                        # Check if book is already owned
                        if book_info.get('already_owned'):
                            logger.info(f"Marking {asin} as inactive (already owned)")
                            if not dry_run:
                                db.mark_book_deleted(asin)
                            continue

                        current_price = book_info['current_price']
                        list_price = book_info['list_price']

                        # Upsert book metadata with latest scraped data
                        scraped_title = book_info['title']
                        scraped_author = book_info['author']
                        scraped_cover = book_info['cover_url']

                        # Use scraped data if available, otherwise keep existing
                        title = scraped_title or book['title'] or asin
                        author = scraped_author or book['author']
                        cover_url = scraped_cover or book['cover_url']

                        # Update metadata if we got any new data from scraping
                        if scraped_title or scraped_author or scraped_cover:
                            logger.debug(f"Updating metadata for {asin}")
                            if not dry_run:
                                db.update_book_metadata(asin, title, author, cover_url)

                        # Handle free books (price could be 0 or None)
                        if current_price is None:
                            logger.warning(f"Could not determine price for {title}")
                            continue

                        # If no list price, use current price
                        if list_price is None:
                            list_price = current_price

                        # Get previous price before saving new price history
                        previous_price = db.get_previous_price(asin)

                        # Save price history
                        if not dry_run:
                            db.add_price_history(asin, current_price, list_price)

                        # Check if should notify
                        last_notification = db.get_last_notification(asin)
                        last_notified_price = float(last_notification['notified_price']) if last_notification and last_notification['notified_price'] is not None else None

                        if should_notify(current_price, list_price, last_notified_price):
                            savings_percent = calculate_savings_percent(current_price, list_price)

                            deal = {
                                'asin': asin,
                                'title': title,
                                'author': author,
                                'cover_url': cover_url,
                                'current_price': current_price,
                                'list_price': list_price,
                                'previous_price': previous_price,
                                'savings_percent': savings_percent
                            }
                            deals_found.append(deal)

                            # Record notification
                            if not dry_run:
                                db.add_notification(asin, current_price)

                            # Log with proper formatting (handle free books)
                            if current_price == 0:
                                logger.info(f"Deal found: {title} - FREE (100% off)")
                            else:
                                logger.info(f"Deal found: {title} - ${current_price:.2f} ({savings_percent}% off)")

                        # Delay between checks to avoid rate limiting
                        time.sleep(check_delay / 1000)

                    except Exception as e:
                        logger.error(f"Failed to process {asin}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

            # Phase 2: Check daily deals
            if not skip_daily and not target_asin:
                daily_deals = check_daily_deals_phase(page, db, check_delay, dry_run)
                deals_found.extend(daily_deals)

        finally:
            page.close()

    # Send email if deals found
    if deals_found and not dry_run:
        logger.info(f"Sending email for {len(deals_found)} deals...")

        notifier = EmailNotifier(
            smtp_server=config.get('email.smtp_server'),
            smtp_port=config.get('email.smtp_port'),
            from_address=config.get('email.from_address'),
            password=config.get_email_password()
        )

        html = EmailNotifier.generate_email_html(deals_found)
        today = datetime.now().strftime('%Y-%m-%d')
        subject = f"Kindle Deals {today}: {len(deals_found)} book(s) on sale!"
        to_address = config.get('email.to_address')

        notifier.send_email(to_address, subject, html)
        logger.info("Email sent successfully")
    elif deals_found and dry_run:
        logger.info(f"DRY RUN: Would send email for {len(deals_found)} deals:")
        for deal in deals_found:
            logger.info(f"  - {deal['title']} (${deal['current_price']:.2f})")
    else:
        logger.info("No deals found")


def send_notification_for_recent_deals(config: Config, db: Database, hours: int = 24):
    """Send email notification for recent deals found in the database"""
    import mysql.connector

    # Get recent notifications
    cursor = db.conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT n.asin, n.notified_price, n.notified_date,
               b.title, b.author, b.cover_url,
               ph.list_price
        FROM notifications n
        JOIN books b ON n.asin = b.asin
        LEFT JOIN price_history ph ON n.asin = ph.asin
            AND ph.check_date = (
                SELECT MAX(check_date) FROM price_history WHERE asin = n.asin
            )
        WHERE n.notified_date >= DATE_SUB(NOW(), INTERVAL %s HOUR)
        ORDER BY n.notified_date DESC
    """, (hours,))

    notifications = cursor.fetchall()

    if not notifications:
        logger.info(f"No deals found in the last {hours} hours")
        return

    # Convert to deals format
    deals = []
    for notif in notifications:
        list_price = notif['list_price'] or notif['notified_price']
        savings_percent = calculate_savings_percent(notif['notified_price'], list_price)

        deals.append({
            'asin': notif['asin'],
            'title': notif['title'] or notif['asin'],
            'author': notif['author'],
            'cover_url': notif['cover_url'],
            'current_price': notif['notified_price'],
            'list_price': list_price,
            'savings_percent': savings_percent
        })

    # Send email
    logger.info(f"Sending email for {len(deals)} recent deals...")

    notifier = EmailNotifier(
        smtp_server=config.get('email.smtp_server'),
        smtp_port=config.get('email.smtp_port'),
        from_address=config.get('email.from_address'),
        password=config.get_email_password()
    )

    html = EmailNotifier.generate_email_html(deals)
    today = datetime.now().strftime('%Y-%m-%d')
    subject = f"Kindle Deals {today}: {len(deals)} book(s) on sale!"
    to_address = config.get('email.to_address')

    notifier.send_email(to_address, subject, html)
    logger.info("Email sent successfully")


def main():
    parser = argparse.ArgumentParser(description='Check for Kindle deals')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--asin', help='Check specific ASIN')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--dry-run', action='store_true',
                        help='Check deals but don\'t send email or update database')
    parser.add_argument('--force', action='store_true',
                        help='Force check all books, even if already checked today')
    parser.add_argument('--skip-samples', action='store_true',
                        help='Skip checking sample book prices')
    parser.add_argument('--skip-daily', action='store_true',
                        help='Skip checking daily deals page')
    parser.add_argument('--send-notification', action='store_true',
                        help='Send email for recent deals without checking prices')
    parser.add_argument('--hours', type=int, default=24,
                        help='Hours to look back for recent deals (default: 24)')

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

        if args.send_notification:
            send_notification_for_recent_deals(config, db, args.hours)
        else:
            check_deals(config, db, target_asin=args.asin, force=args.force, dry_run=args.dry_run, skip_samples=args.skip_samples, skip_daily=args.skip_daily)

        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
