# Daily Deals Matcher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add daily Kindle deal discovery that filters 50-100+ deals to only books matching user's reading interests (same author, series, or Amazon recommendations).

**Architecture:** Scrape Amazon's daily deals page, check each deal against user's sample library using three signals (author/series/recommendations), send filtered matches via existing email system.

**Tech Stack:** Python 3.7, Playwright (web scraping), MySQL (storage), existing email infrastructure

---

## Task 1: Add Database Schema for Recommendations

**Files:**
- Modify: `src/database.py:53-120` (add tables in `_create_tables`)
- Test: Manual verification via MySQL

**Step 1: Add recommendations table creation**

In `src/database.py`, add after notifications table creation (around line 100):

```python
        # Recommendations table - stores "also bought" data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                source_asin VARCHAR(20) NOT NULL,
                recommended_asin VARCHAR(20) NOT NULL,
                created_date DATETIME NOT NULL,
                FOREIGN KEY (source_asin) REFERENCES books(asin),
                UNIQUE KEY unique_recommendation (source_asin, recommended_asin)
            )
        """)

        # Deal checks table - tracks processed daily deals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deal_checks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                asin VARCHAR(20) NOT NULL,
                check_date DATE NOT NULL,
                was_deal TINYINT(1) NOT NULL,
                notified TINYINT(1) NOT NULL,
                UNIQUE KEY unique_daily_check (asin, check_date)
            )
        """)
```

**Step 2: Test table creation**

Run: `python -c "from src.database import Database; from src.config import Config; db = Database(**Config('config.yaml').get('database')); print('Tables created')"`

Expected: "Tables created" with no errors

**Step 3: Verify tables in MySQL**

Run:
```bash
mysql -u root -p -e "USE kindle_deals; SHOW TABLES;"
```

Expected: See `recommendations` and `deal_checks` in the list

**Step 4: Commit**

```bash
git add src/database.py
git commit -m "feat: add recommendations and deal_checks tables

- recommendations: stores Amazon 'also bought' data
- deal_checks: tracks processed daily deals

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Add Database Methods for Recommendations

**Files:**
- Modify: `src/database.py` (add after existing methods, around line 320)
- Test: Manual testing with Python REPL

**Step 1: Add method to store recommendation**

Add to `Database` class:

```python
    def add_recommendation(self, source_asin: str, recommended_asin: str) -> None:
        """
        Add a recommendation (also bought) for a book.

        Args:
            source_asin: The book that has the recommendation
            recommended_asin: The recommended book ASIN
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO recommendations (source_asin, recommended_asin, created_date)
                VALUES (%s, %s, %s)
            """, (source_asin, recommended_asin, datetime.now()))
            self.conn.commit()
        except mysql.connector.IntegrityError:
            # Duplicate recommendation - already exists, ignore
            pass
```

**Step 2: Add method to get recommendations for a book**

```python
    def get_recommendations(self, source_asin: str) -> List[str]:
        """
        Get all recommended ASINs for a source book.

        Args:
            source_asin: The book to get recommendations for

        Returns:
            List of recommended ASINs
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT recommended_asin FROM recommendations
            WHERE source_asin = %s
        """, (source_asin,))
        results = cursor.fetchall()
        return [row[0] for row in results]
```

**Step 3: Add method to check if book has recommendations**

```python
    def has_recommendations(self, source_asin: str) -> bool:
        """
        Check if we've already scraped recommendations for this book.

        Args:
            source_asin: The book to check

        Returns:
            True if recommendations exist, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM recommendations
            WHERE source_asin = %s
        """, (source_asin,))
        count = cursor.fetchone()[0]
        return count > 0
```

**Step 4: Add method to get all recommended ASINs**

```python
    def get_all_recommended_asins(self) -> Dict[str, str]:
        """
        Get all recommended ASINs with their source book titles.

        Returns:
            Dict mapping recommended_asin -> source_book_title
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.recommended_asin, b.title
            FROM recommendations r
            JOIN books b ON r.source_asin = b.asin
            WHERE b.is_active = 1
        """)
        results = cursor.fetchall()
        return {row['recommended_asin']: row['title'] or 'Unknown' for row in results}
```

**Step 5: Test methods**

Run:
```python
from src.database import Database
from src.config import Config
db = Database(**Config('config.yaml').get('database'))

# Test add
db.add_recommendation('B000TEST', 'B000REC1')
db.add_recommendation('B000TEST', 'B000REC2')

# Test get
recs = db.get_recommendations('B000TEST')
print(f"Recommendations: {recs}")  # Should show ['B000REC1', 'B000REC2']

# Test has
has = db.has_recommendations('B000TEST')
print(f"Has recommendations: {has}")  # Should be True
```

Expected: No errors, correct output

**Step 6: Commit**

```bash
git add src/database.py
git commit -m "feat: add recommendation database methods

- add_recommendation: store also-bought data
- get_recommendations: retrieve recs for a book
- has_recommendations: check if already scraped
- get_all_recommended_asins: get all for matching

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add Database Methods for Deal Checks

**Files:**
- Modify: `src/database.py` (add after recommendation methods)

**Step 1: Add method to record deal check**

```python
    def add_deal_check(self, asin: str, was_deal: bool, notified: bool) -> None:
        """
        Record that we checked a daily deal.

        Args:
            asin: Book ASIN
            was_deal: Whether it met deal criteria
            notified: Whether we sent notification
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO deal_checks (asin, check_date, was_deal, notified)
                VALUES (%s, CURDATE(), %s, %s)
            """, (asin, 1 if was_deal else 0, 1 if notified else 0))
            self.conn.commit()
        except mysql.connector.IntegrityError:
            # Already checked today - ignore
            pass
```

**Step 2: Add method to check if already processed today**

```python
    def was_deal_checked_today(self, asin: str) -> bool:
        """
        Check if we already processed this deal today.

        Args:
            asin: Book ASIN

        Returns:
            True if already checked today, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM deal_checks
            WHERE asin = %s AND check_date = CURDATE()
        """, (asin,))
        count = cursor.fetchone()[0]
        return count > 0
```

**Step 3: Test methods**

Run:
```python
from src.database import Database
from src.config import Config
db = Database(**Config('config.yaml').get('database'))

# Test add
db.add_deal_check('B000DEAL1', was_deal=True, notified=True)
db.add_deal_check('B000DEAL2', was_deal=False, notified=False)

# Test check
checked = db.was_deal_checked_today('B000DEAL1')
print(f"Was checked today: {checked}")  # Should be True

not_checked = db.was_deal_checked_today('B000NEVER')
print(f"Was not checked: {not not_checked}")  # Should be True
```

Expected: Correct boolean results

**Step 4: Commit**

```bash
git add src/database.py
git commit -m "feat: add deal check database methods

- add_deal_check: record daily deal processing
- was_deal_checked_today: avoid duplicate checks

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add Recommendation Scraping to sync_library

**Files:**
- Modify: `src/sync_library.py`
- Test: Manual run with `--verbose`

**Step 1: Add function to scrape recommendations**

Add at top of file, after imports:

```python
def scrape_recommendations(page, asin: str) -> List[str]:
    """
    Scrape 'Customers who bought this also bought' ASINs from product page.

    Args:
        page: Playwright page object
        asin: Book ASIN to scrape recommendations for

    Returns:
        List of recommended ASINs
    """
    try:
        url = f"https://www.amazon.com/dp/{asin}"
        logger.debug(f"Scraping recommendations from {url}")
        page.goto(url, wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(2000)

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
                            import re
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
```

**Step 2: Add recommendation scraping to sync flow**

Find the section where books are synced (after `db.add_book()` calls), add:

```python
            logger.info(f"Successfully synced {len(synced_asins)} samples")

            # NEW: Scrape recommendations for samples
            logger.info("Scraping recommendations for samples...")
            rec_count = 0
            for sample in samples:
                asin = sample['asin']

                # Skip if we already have recommendations
                if db.has_recommendations(asin):
                    logger.debug(f"Skipping {asin} - already has recommendations")
                    continue

                # Scrape recommendations
                recs = scrape_recommendations(page, asin)

                # Store in database
                for rec_asin in recs:
                    db.add_recommendation(asin, rec_asin)
                    rec_count += 1

                # Add delay to avoid rate limiting
                page.wait_for_timeout(3000)

            logger.info(f"Stored {rec_count} recommendations")
```

**Step 3: Test with dry run on a few books**

Run: `python src/sync_library.py --verbose`

Expected:
- See "Scraping recommendations for samples..."
- See "Found X unique recommendations for..." logs
- See "Stored X recommendations" at end
- No crashes or CAPTCHA blocks

**Step 4: Verify recommendations in database**

Run:
```bash
mysql -u root -p -e "USE kindle_deals; SELECT COUNT(*) FROM recommendations;"
```

Expected: Non-zero count

**Step 5: Commit**

```bash
git add src/sync_library.py
git commit -m "feat: scrape Amazon recommendations during sync

- Add scrape_recommendations() function
- Scrape 'also bought' data for each sample
- Store in recommendations table
- Skip books already scraped

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Create Similarity Matcher Module

**Files:**
- Create: `src/similarity_matcher.py`
- Test: Manual testing with Python REPL

**Step 1: Create similarity matcher class**

Create new file `src/similarity_matcher.py`:

```python
"""Similarity matching for daily deals based on user's sample library."""

import re
from typing import Tuple, Set, Dict
from database import Database


class SimilarityMatcher:
    """Matches deal books against user's reading interests."""

    def __init__(self, db: Database):
        """
        Initialize matcher with cached data from database.

        Args:
            db: Database instance
        """
        self.db = db

        # Cache sets for fast O(1) lookups
        self.sample_authors: Set[str] = set()
        self.sample_series: Set[str] = set()
        self.recommended_asins: Dict[str, str] = {}

        self._load_cache()

    def _load_cache(self) -> None:
        """Load matching data from database into memory."""
        # Get all active sample books
        books = self.db.get_active_books()

        for book in books:
            # Store author (normalized)
            author = book.get('author')
            if author:
                self.sample_authors.add(author.lower().strip())

            # Extract series from title
            title = book.get('title')
            if title:
                series = self._extract_series(title)
                if series:
                    self.sample_series.add(series.lower().strip())

        # Get all recommended ASINs
        self.recommended_asins = self.db.get_all_recommended_asins()

    def _extract_series(self, title: str) -> str:
        """
        Extract series name from book title.

        Common patterns:
        - "Book Title (Series Name, Book 1)"
        - "Book Title (Series Name #1)"
        - "Series Name: Book Title"

        Args:
            title: Book title

        Returns:
            Series name or empty string if not found
        """
        # Pattern: "Title (Series, Book N)" or "Title (Series #N)"
        match = re.search(r'\(([^,#)]+)[,#]', title)
        if match:
            return match.group(1).strip()

        # Pattern: "Series: Title"
        if ':' in title:
            parts = title.split(':', 1)
            # Only consider it a series if first part is reasonably short
            if len(parts[0]) < 50:
                return parts[0].strip()

        return ''

    def is_match(self, asin: str, author: str, title: str) -> Tuple[bool, str]:
        """
        Check if deal book matches user's interests.

        Checks three signals in priority order:
        1. Same author as a sample book
        2. Same series as a sample book
        3. Recommended from a sample book

        Args:
            asin: Deal book ASIN
            author: Deal book author
            title: Deal book title

        Returns:
            (is_match: bool, reason: str)

        Examples:
            (True, "Same author: Brandon Sanderson")
            (True, "Same series: Mistborn")
            (True, "Recommended from: The Way of Kings")
            (False, "")
        """
        # Check 1: Author match
        if author:
            normalized_author = author.lower().strip()
            if normalized_author in self.sample_authors:
                return (True, f"Same author: {author}")

        # Check 2: Series match
        series = self._extract_series(title)
        if series:
            normalized_series = series.lower().strip()
            if normalized_series in self.sample_series:
                return (True, f"Same series: {series}")

        # Check 3: Recommendation match
        if asin in self.recommended_asins:
            source_title = self.recommended_asins[asin]
            return (True, f"Recommended from: {source_title}")

        return (False, "")
```

**Step 2: Test the matcher**

Run:
```python
from src.database import Database
from src.config import Config
from src.similarity_matcher import SimilarityMatcher

db = Database(**Config('config.yaml').get('database'))
matcher = SimilarityMatcher(db)

# Test with a known author (replace with actual from your DB)
is_match, reason = matcher.is_match('B000TEST', 'Brandon Sanderson', 'Test Book')
print(f"Match: {is_match}, Reason: {reason}")

# Test series extraction
series = matcher._extract_series("Mistborn (Mistborn, Book 1)")
print(f"Extracted series: {series}")  # Should be "Mistborn"
```

Expected: Correct matching based on your sample data

**Step 3: Commit**

```bash
git add src/similarity_matcher.py
git commit -m "feat: add similarity matcher for daily deals

- Match by author (exact match)
- Match by series (extracted from title)
- Match by recommendations (from also-bought data)
- Cache data in memory for fast lookups

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Create Daily Deals Scraper Script

**Files:**
- Create: `src/check_daily_deals.py`
- Test: Manual run with dry-run mode

**Step 1: Create script with basic structure**

Create new file `src/check_daily_deals.py`:

```python
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
```

**Step 2: Test with dry run**

Run: `python src/check_daily_deals.py --dry-run --verbose`

Expected:
- Scrapes daily deals page
- Checks each against matcher
- Logs matches found
- Shows "DRY RUN: Would send email..."

**Step 3: Commit**

```bash
git add src/check_daily_deals.py
git commit -m "feat: add daily deals checker script

- Scrape Amazon's daily Kindle deals page
- Check each deal against similarity matcher
- Track processed deals in database
- Send email for matches (placeholder)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Add Match Reason to Email Template

**Files:**
- Modify: `src/email_notifier.py`

**Step 1: Add CSS for match reason badge**

In the `<style>` section of `generate_email_html()`, add:

```css
        .match-reason {
            font-size: 13px;
            color: #067d62;
            margin: 8px 0 12px 0;
            font-weight: 600;
            padding: 4px 0;
        }
        .match-reason::before {
            content: "✓ ";
            font-weight: bold;
        }
```

**Step 2: Add match reason display in email body**

In the section where author is displayed, add after the author div:

```python
            # Add author if available
            if author:
                html += f"""
                <div class="book-author">by {author}</div>
"""

            # Add match reason if available (for daily deals)
            match_reason = book.get('match_reason')
            if match_reason:
                html += f"""
                <div class="match-reason">{html_lib.escape(match_reason)}</div>
"""
```

**Step 3: Test with modified send_notification.py**

Modify test data in `src/send_notification.py` to include match_reason:

```python
test_books = [
    {
        'asin': 'B01234ABCD',
        'title': 'The Art of Computer Programming, Vol. 1',
        'author': 'Donald Knuth',
        'cover_url': 'https://m.media-amazon.com/images/I/41f5MZ8Y2JL.jpg',
        'current_price': 1.99,
        'list_price': 19.99,
        'previous_price': 4.99,
        'match_reason': 'Same author: Donald Knuth'  # NEW
    },
    # ... add to others too
]
```

Run: `python src/send_notification.py --test`

Expected: Email shows green "✓ Same author: ..." badge under each book

**Step 4: Commit**

```bash
git add src/email_notifier.py src/send_notification.py
git commit -m "feat: add match reason badge to email template

- Display why each deal matched (author/series/rec)
- Green badge with checkmark
- Escape match reason text for safety

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Add Cron Job and Documentation

**Files:**
- Modify: `CLAUDE.md`
- Create: `cron_example.txt`

**Step 1: Create cron example file**

Create `cron_example.txt`:

```bash
# Kindle Deals Monitor - Cron Schedule

# Check daily deals at 5 AM
0 5 * * * cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_daily_deals.py

# Check sample prices at 6 AM
0 6 * * * cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_deals.py

# Sync Kindle library weekly on Sunday at 5 AM
0 5 * * 0 cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/sync_library.py
```

**Step 2: Update CLAUDE.md**

Add to "Running Scripts" section:

```markdown
### Running Scripts
```bash
# Sync Kindle library from Amazon "My Books" page
python src/sync_library.py

# Check for deals on tracked books
python src/check_deals.py

# Check specific book by ASIN
python src/check_deals.py --asin B01234567X

# Check today's daily deals for matches
python src/check_daily_deals.py

# Dry run daily deals (don't send email)
python src/check_daily_deals.py --dry-run

# Send test email notification
python src/send_notification.py --test
```

### Cron Schedule

```bash
# Check daily deals at 5 AM
0 5 * * * cd /path/to/kindle-deals && source venv/bin/activate && python src/check_daily_deals.py

# Check sample prices at 6 AM
0 6 * * * cd /path/to/kindle-deals && source venv/bin/activate && python src/check_deals.py

# Sync library weekly on Sunday at 5 AM
0 5 * * 0 cd /path/to/kindle-deals && source venv/bin/activate && python src/sync_library.py
```
```

**Step 3: Update architecture section**

Add to "Core Modules":

```markdown
6. **similarity_matcher.py** - Book similarity matching
   - Matches books by author, series, or recommendations
   - Caches data in memory for fast lookups
   - Used by daily deals checker

### Scripts

1. **sync_library.py** - Syncs your Kindle library from Amazon "My Books" page using Playwright
   - Also scrapes "also bought" recommendations for each sample
2. **check_deals.py** - Checks book prices via web scraping and sends notifications
3. **check_daily_deals.py** - Checks Amazon's daily deals for books matching your interests
4. **send_notification.py** - Sends test email notifications
```

**Step 4: Commit**

```bash
git add CLAUDE.md cron_example.txt
git commit -m "docs: add daily deals documentation and cron examples

- Document check_daily_deals.py script
- Add cron schedule examples
- Update architecture section

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Final Integration Test

**Files:**
- Test: All components together

**Step 1: Run full sync with recommendations**

Run: `python src/sync_library.py --verbose`

Expected:
- Syncs samples
- Scrapes recommendations for each
- No errors

**Step 2: Verify recommendations in database**

Run:
```bash
mysql -u root -p -e "USE kindle_deals; SELECT COUNT(*) as rec_count FROM recommendations;"
```

Expected: Should show recommendation count

**Step 3: Run daily deals check (dry run)**

Run: `python src/check_daily_deals.py --dry-run --verbose`

Expected:
- Scrapes daily deals
- Checks similarity
- Shows matches (if any)
- No errors

**Step 4: Run actual daily deals check**

Run: `python src/check_daily_deals.py --verbose`

Expected:
- Sends email if matches found
- Updates deal_checks table

**Step 5: Verify deal checks in database**

Run:
```bash
mysql -u root -p -e "USE kindle_deals; SELECT * FROM deal_checks LIMIT 10;"
```

Expected: Shows processed deals

**Step 6: Final commit**

```bash
git add .
git commit -m "test: verify daily deals matcher end-to-end

All components tested and working:
- Database tables created
- Recommendations scraped during sync
- Similarity matching functional
- Daily deals scraping working
- Email notifications sent

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Implementation Complete!

**Next steps:**
1. Set up cron jobs using `cron_example.txt`
2. Monitor first week for any errors or CAPTCHA blocks
3. Adjust delays if needed to avoid rate limiting
4. Enjoy discovering relevant Kindle deals daily!

**Troubleshooting:**
- If CAPTCHA appears: Increase delays in `check_daily_deals.py`
- If no matches: Check `similarity_matcher.py` is loading data correctly
- If email fails: Check SMTP settings in `config.yaml`
