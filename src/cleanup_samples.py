#!/usr/bin/env python3
"""
List (and optionally open) Amazon URLs for samples that have an owned copy.

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
"""
import argparse
import logging
import sys
import webbrowser
from typing import Optional
from urllib.parse import quote

from config import Config
from database import Database

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


def main():
    parser = argparse.ArgumentParser(
        description="List samples with owned copies that can be deleted from Kindle library"
    )
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument(
        '--open', action='store_true',
        help='Open each URL in a new browser tab automatically'
    )
    args = parser.parse_args()

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
