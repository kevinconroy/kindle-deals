#!/usr/bin/env python3
"""
List, open, or delete Kindle samples that have an owned copy.

A Kindle library can contain both a sample and a purchased copy of the same
book under the same ASIN. The sample is redundant once you own the book.
This script finds those books in the database and outputs URLs you can use
to navigate directly to each item in the Amazon digital console and delete
the sample.

Usage:
    # List URLs
    python src/cleanup_samples.py

    # Open all URLs in browser tabs automatically
    python src/cleanup_samples.py --open

    # Delete the samples from the Amazon library (purchased + dual-state books)
    python src/cleanup_samples.py --delete
    python src/cleanup_samples.py --delete --dry-run
    python src/cleanup_samples.py --delete --asin B003XT60E0
"""
import argparse
import logging
import os
import sys
import webbrowser
from typing import Optional
from urllib.parse import quote

from check_deals import scrape_book_title_author
from config import Config
from database import Database
from sample_cleaner import Outcome, SessionExpired, delete_sample
from scraper import AmazonScraper
from sync_library import resolve_headless

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CONSOLE_BASE = "https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc"


def make_cleanup_url(title: Optional[str]) -> str:
    """Return the digital-console URL for a book title, or the base URL if unknown."""
    if title:
        return f"{CONSOLE_BASE}/{quote(title, safe=':')}"
    return CONSOLE_BASE


def delete_samples(config: Config, db: Database, books: list, dry_run: bool,
                   headless_override: Optional[bool] = None) -> dict:
    """
    Delete each book's sample from the Amazon library and record the result.

    Returns {Outcome: [book, ...]} grouping each book by what happened. Stops early (and exits 2)
    if the digital console demands a sign-in.
    """
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    headless = resolve_headless(config, headless_override)
    domain = config.get('amazon.domain', 'amazon.com')
    action_delay = config.get('scraping.action_delay', 500)
    results = {outcome: [] for outcome in Outcome}

    with AmazonScraper(session_path, headless) as scraper:
        page = scraper.new_page()
        try:
            for book in books:
                asin = book['asin']
                if not book.get('title'):
                    # The sync flags dual-state books before check_deals ever scrapes
                    # them, so they can reach here untitled; the console needs a title.
                    info = scrape_book_title_author(page, asin, domain, scraper)
                    if info and info.get('title'):
                        book['title'] = info['title']
                        if not dry_run:
                            db.update_book_metadata(asin, info['title'], info.get('author'))
                        logger.info(f"{asin}: fetched title '{info['title']}'")
                try:
                    outcome = delete_sample(page, asin, book.get('title'), domain,
                                            dry_run=dry_run, action_delay=action_delay)
                except SessionExpired as e:
                    scraper.mark_session_invalid()
                    logger.error(f"{e}. Sign in with `python src/sync_library.py --login`, then retry.")
                    sys.exit(2)
                except Exception as e:
                    logger.error(f"{asin}: unexpected error: {e}")
                    outcome = Outcome.FAILED
                results[outcome].append(book)
                if dry_run:
                    pass
                elif outcome in (Outcome.DELETED, Outcome.ALREADY_GONE):
                    db.mark_sample_removed(asin)
                elif outcome == Outcome.NO_OWNED_COPY and db.clear_unowned_flag(asin):
                    logger.info(f"{asin}: not owned after all, returned to deal tracking")
        finally:
            page.close()
    return results


REPORT_HEADINGS = {
    Outcome.DELETED: "Sample deleted (owned copy verified)",
    Outcome.ALREADY_GONE: "Owned, no sample left in library",
    Outcome.DRY_RUN: "Owned + sample present (would delete)",
    Outcome.NO_OWNED_COPY: "Sample kept: only the sample is in the library",
    Outcome.NOT_FOUND: "Sample kept: console search found neither copy",
    Outcome.NO_TITLE: "Skipped: no title in database to search by",
    Outcome.FAILED: "FAILED (sample left in place)",
}


def print_report(results: dict) -> None:
    """Print each book grouped by cleanup outcome."""
    for outcome, heading in REPORT_HEADINGS.items():
        books = results[outcome]
        if not books:
            continue
        print(f"\n{heading} ({len(books)}):")
        for book in books:
            print(f"  {book['asin']}  {book.get('title') or '(untitled)'}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="List samples with owned copies that can be deleted from Kindle library"
    )
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument(
        '--open', action='store_true',
        help='Open each URL in a new browser tab automatically'
    )
    parser.add_argument(
        '--delete', action='store_true',
        help='Delete samples of purchased/owned books from the Amazon library'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='With --delete: verify each book but delete nothing')
    parser.add_argument('--asin', action='append',
                        help='With --delete: only this ASIN (repeatable)')
    parser.add_argument('--limit', type=int, help='With --delete: at most N books')
    parser.add_argument('--headless', type=lambda x: x.lower() == 'true', default=None,
                        help='Override headless mode (true/false)')
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
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    if args.delete:
        books = db.get_sample_cleanup_candidates()
        if args.asin:
            books = [b for b in books if b['asin'] in set(args.asin)]
        if args.limit:
            books = books[:args.limit]
        if not books:
            print("No samples to clean up.")
            db.close()
            sys.exit(0)
        logger.info(f"Cleaning up {len(books)} sample(s){' (dry run)' if args.dry_run else ''}")
        results = delete_samples(config, db, books, args.dry_run, args.headless)
        db.close()
        print_report(results)
        sys.exit(1 if results[Outcome.FAILED] else 0)

    books = db.get_samples_with_owned_copies()
    db.close()

    if not books:
        print("No samples with owned copies found — nothing to clean up.")
        sys.exit(0)

    print(f"Found {len(books)} sample(s) with an owned copy:\n")

    urls = []
    for book in books:
        title = book.get('title') or book['asin']
        author = book.get('author') or 'Unknown author'
        url = make_cleanup_url(book.get('title'))
        urls.append(url)
        print(f"  {title}")
        print(f"  by {author}")
        print(f"  {url}")
        print()

    if args.open:
        print(f"Opening {len(urls)} URL(s) in browser...")
        for url in urls:
            webbrowser.open_new_tab(url)
        print("Done. Delete each sample from the page that opens, then close the tabs.")
    else:
        print(f"Run with --open to open all {len(urls)} URL(s) in browser tabs automatically.")


if __name__ == '__main__':
    main()
