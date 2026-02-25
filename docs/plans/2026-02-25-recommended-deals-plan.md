# Recommended Deals Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Proactively check prices for all recommended book ASINs using parallel Playwright tabs, and display qualifying deals in a separate "Recommended Deals" email section.

**Architecture:** New Phase 3 in `check_deals.py` uses a `ThreadPoolExecutor` with a pool of Playwright pages to scrape recommended book prices concurrently. Recommended books are added to the `books` table (marked `is_recommendation=1`) so they can reuse existing `price_history`, `notifications`, and `deal_checks` tables. The email template gains a two-section layout.

**Tech Stack:** Python, MySQL (mysql-connector-python), Playwright (sync API), concurrent.futures.ThreadPoolExecutor

---

### Task 1: Add `is_recommendation` Column and Migration

**Files:**
- Modify: `src/database.py:59-68` (books CREATE TABLE)
- Modify: `src/database.py:70-102` (migration section)

**Step 1: Update CREATE TABLE statement**

In `src/database.py`, modify the `_create_tables` method's books table definition (line 59-68) to include the new column:

```python
        # Books table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                asin VARCHAR(20) PRIMARY KEY,
                title VARCHAR(500),
                author VARCHAR(255),
                cover_url VARCHAR(1000),
                date_added DATETIME NOT NULL,
                is_sample TINYINT(1) DEFAULT 1,
                is_deleted TINYINT(1) DEFAULT 0,
                is_recommendation TINYINT(1) DEFAULT 0
            )
        """)
```

**Step 2: Add migration for existing databases**

After the existing `is_active -> is_sample + is_deleted` migration block (around line 102), add:

```python
        # Migrate: add is_recommendation column (for existing databases)
        try:
            cursor.execute("""
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'books' AND COLUMN_NAME = 'is_recommendation'
            """, (self.database,))
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE books ADD COLUMN is_recommendation TINYINT(1) DEFAULT 0")
                self.conn.commit()
        except Exception:
            pass
```

**Step 3: Run existing tests to verify no regressions**

Run: `pytest tests/test_database.py -v`
Expected: All existing tests PASS (the new column defaults to 0 for existing rows)

**Step 4: Commit**

```bash
git add src/database.py
git commit -m "feat(db): add is_recommendation column to books table"
```

---

### Task 2: Add New Database Methods

**Files:**
- Modify: `src/database.py` (add methods after `was_deal_checked_today`, around line 489)
- Test: `tests/test_database.py`

**Step 1: Write failing tests for the three new methods**

Add to `tests/test_database.py`:

```python
def test_get_unchecked_recommendation_asins(clean_db):
    """Test getting recommendation ASINs not yet checked today."""
    # Add sample books
    clean_db.add_book(asin='B001', title='Sample Book 1')
    clean_db.add_book(asin='B002', title='Sample Book 2')

    # Add recommendations
    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B001', 'R002')
    clean_db.add_recommendation('B002', 'R003')

    # All three should be unchecked
    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert set(unchecked) == {'R001', 'R002', 'R003'}

    # Mark one as checked today
    clean_db.add_deal_check('R001', was_deal=False, notified=False)

    # Now only two should be unchecked
    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert set(unchecked) == {'R002', 'R003'}


def test_get_unchecked_recommendation_asins_excludes_deleted_sources(clean_db):
    """Test that recommendations from deleted source books are excluded."""
    clean_db.add_book(asin='B001', title='Active Sample')
    clean_db.add_book(asin='B002', title='Deleted Sample')
    clean_db.mark_book_deleted('B002')

    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B002', 'R002')

    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert unchecked == ['R001']


def test_add_recommendation_book_new(clean_db):
    """Test adding a new recommendation book."""
    clean_db.add_recommendation_book('R001', 'Rec Book', 'Rec Author', 'https://example.com/cover.jpg')

    book = clean_db.get_book('R001')
    assert book is not None
    assert book['title'] == 'Rec Book'
    assert book['author'] == 'Rec Author'
    assert book['is_sample'] == 0
    assert book['is_recommendation'] == 1


def test_add_recommendation_book_existing_sample(clean_db):
    """Test that adding a recommendation book doesn't override existing sample."""
    # Book already exists as a sample
    clean_db.add_book(asin='B001', title='My Sample', author='Original Author')

    # Try to add as recommendation - should update metadata but keep is_sample=1
    clean_db.add_recommendation_book('B001', 'Updated Title', 'Updated Author', 'https://example.com/new.jpg')

    book = clean_db.get_book('B001')
    assert book['is_sample'] == 1  # Preserved
    assert book['is_recommendation'] == 0  # Not changed to recommendation
    assert book['title'] == 'Updated Title'  # Metadata updated


def test_add_recommendation_book_updates_metadata(clean_db):
    """Test that re-adding a recommendation book updates metadata."""
    clean_db.add_recommendation_book('R001', None, None, None)
    clean_db.add_recommendation_book('R001', 'Now Has Title', 'Now Has Author', 'https://example.com/cover.jpg')

    book = clean_db.get_book('R001')
    assert book['title'] == 'Now Has Title'
    assert book['author'] == 'Now Has Author'


def test_get_recommendation_source(clean_db):
    """Test getting source book title for a recommendation."""
    clean_db.add_book(asin='B001', title='The Way of Kings', author='Brandon Sanderson')
    clean_db.add_recommendation('B001', 'R001')

    source_title = clean_db.get_recommendation_source('R001')
    assert source_title == 'The Way of Kings'


def test_get_recommendation_source_not_found(clean_db):
    """Test getting source for a non-existent recommendation."""
    source_title = clean_db.get_recommendation_source('NOTEXIST')
    assert source_title is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py::test_get_unchecked_recommendation_asins -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_unchecked_recommendation_asins'`

**Step 3: Implement the three new methods**

Add to `src/database.py` after the `was_deal_checked_today` method (after line 489):

```python
    def get_unchecked_recommendation_asins(self) -> List[str]:
        """
        Get all recommended ASINs that haven't been checked today.

        Returns ASINs from recommendations table where the source book
        is an active sample, excluding any already in deal_checks for today.

        Returns:
            List of recommended ASIN strings
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT r.recommended_asin
            FROM recommendations r
            JOIN books b ON r.source_asin = b.asin
            WHERE b.is_sample = 1 AND b.is_deleted = 0
            AND r.recommended_asin NOT IN (
                SELECT asin FROM deal_checks WHERE check_date = CURDATE()
            )
        """)
        results = cursor.fetchall()
        return [row[0] for row in results]

    def add_recommendation_book(self, asin: str, title: str = None,
                                author: str = None, cover_url: str = None) -> None:
        """
        Add or update a book discovered via recommendations.

        If the book doesn't exist, inserts with is_recommendation=1, is_sample=0.
        If the book already exists (e.g., as a sample), only updates metadata
        (title, author, cover_url) without changing is_sample or is_recommendation.

        Args:
            asin: Amazon Standard Identification Number
            title: Book title (optional)
            author: Book author (optional)
            cover_url: URL to book cover image (optional)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO books (asin, title, author, cover_url, date_added, is_sample, is_deleted, is_recommendation)
            VALUES (%s, %s, %s, %s, %s, 0, 0, 1)
            ON DUPLICATE KEY UPDATE
                title = COALESCE(%s, title),
                author = COALESCE(%s, author),
                cover_url = COALESCE(%s, cover_url)
        """, (asin, title, author, cover_url, datetime.now(), title, author, cover_url))
        self.conn.commit()

    def get_recommendation_source(self, asin: str) -> Optional[str]:
        """
        Get the source book title for a recommended ASIN.

        Args:
            asin: The recommended book's ASIN

        Returns:
            Source book title, or None if not found
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT b.title
            FROM recommendations r
            JOIN books b ON r.source_asin = b.asin
            WHERE r.recommended_asin = %s
            AND b.is_sample = 1 AND b.is_deleted = 0
            LIMIT 1
        """, (asin,))
        result = cursor.fetchone()
        return result['title'] if result else None
```

**Step 4: Run all new tests**

Run: `pytest tests/test_database.py -v -k "recommendation"`
Expected: All 7 new tests PASS

**Step 5: Run full test suite**

Run: `pytest tests/test_database.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat(db): add recommendation book methods"
```

---

### Task 3: Two-Section Email Template

**Files:**
- Modify: `src/email_notifier.py:26-288`
- Test: `tests/test_email_notifier.py`

**Step 1: Write failing tests for the new email structure**

Add to `tests/test_email_notifier.py`:

```python
def test_generate_email_html_two_sections():
    """Test email with both tracked and recommended deals."""
    tracked = [
        {
            'asin': 'B001',
            'title': 'Tracked Book',
            'author': 'Author One',
            'cover_url': 'https://example.com/cover1.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]
    recommended = [
        {
            'asin': 'R001',
            'title': 'Recommended Book',
            'author': 'Author Two',
            'cover_url': 'https://example.com/cover2.jpg',
            'current_price': 1.99,
            'list_price': 12.99,
            'match_reason': 'Recommended from: Tracked Book',
        }
    ]

    html = EmailNotifier.generate_email_html(tracked, recommended_deals=recommended)

    assert 'Tracked Deals' in html
    assert 'Recommended Deals' in html
    assert 'Tracked Book' in html
    assert 'Recommended Book' in html
    assert 'No tracked deals today' not in html


def test_generate_email_html_no_tracked_deals():
    """Test email shows 'No tracked deals today' when tracked section is empty."""
    recommended = [
        {
            'asin': 'R001',
            'title': 'Recommended Book',
            'author': 'Author Two',
            'cover_url': 'https://example.com/cover2.jpg',
            'current_price': 1.99,
            'list_price': 12.99,
            'match_reason': 'Recommended from: Some Book',
        }
    ]

    html = EmailNotifier.generate_email_html([], recommended_deals=recommended)

    assert 'No tracked deals today' in html
    assert 'Recommended Deals' in html
    assert 'Recommended Book' in html


def test_generate_email_html_no_recommended_deals():
    """Test email omits recommended section when empty."""
    tracked = [
        {
            'asin': 'B001',
            'title': 'Tracked Book',
            'author': 'Author One',
            'cover_url': 'https://example.com/cover1.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(tracked, recommended_deals=[])

    assert 'Tracked Deals' in html
    assert 'Tracked Book' in html
    assert 'Recommended Deals' not in html


def test_generate_email_html_backward_compatible():
    """Test that calling without recommended_deals works as before (no section headers)."""
    books = [
        {
            'asin': 'B001',
            'title': 'Test Book',
            'author': 'Author',
            'cover_url': 'https://example.com/cover.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    assert 'Test Book' in html
    # No section headers in backward-compatible mode
    assert 'Tracked Deals' not in html
    assert 'Recommended Deals' not in html
```

**Step 2: Run to verify they fail**

Run: `pytest tests/test_email_notifier.py -v -k "two_sections or no_tracked or no_recommended or backward"`
Expected: FAIL (new test methods reference `recommended_deals` parameter that doesn't exist yet)

**Step 3: Implement the two-section email template**

Refactor `src/email_notifier.py`. The key changes:

1. Extract the per-book HTML generation into a helper method `_generate_book_html(book)`
2. Modify `generate_email_html` to accept optional `recommended_deals` parameter
3. When `recommended_deals` is provided, render two sections; when not, render the flat list (backward compat)

Replace the entire `generate_email_html` method with:

```python
    @staticmethod
    def _generate_book_html(book: Dict[str, Any]) -> str:
        """Generate HTML for a single book card."""
        asin = book['asin']
        title = html_lib.escape(book['title'])
        author = html_lib.escape(book.get('author') or 'Unknown Author')
        cover_url = book.get('cover_url', '')
        current_price = book.get('current_price') or book.get('price', 0)
        list_price = book.get('list_price', 0)
        previous_price = book.get('previous_price')

        if current_price is None:
            current_price = 0

        if list_price and list_price > 0:
            savings_percent = int(((list_price - current_price) / list_price) * 100)
        else:
            savings_percent = 0

        price_drop = None
        price_drop_percent = None
        if previous_price and previous_price > current_price:
            price_drop = previous_price - current_price
            price_drop_percent = int((price_drop / previous_price) * 100)

        amazon_link = f"https://www.amazon.com/dp/{asin}"

        book_html = f"""
    <div class="book">
        <div class="book-content">
"""

        if cover_url:
            book_html += f"""
            <div class="book-cover">
                <img src="{cover_url}" alt="{title}">
            </div>
"""

        book_html += f"""
            <div class="book-details">
                <div class="book-title">{title}</div>
"""

        if author:
            book_html += f"""
                <div class="book-author">by {author}</div>
"""

        match_reason = book.get('match_reason')
        if match_reason:
            book_html += f"""
                <div class="match-reason">{html_lib.escape(match_reason)}</div>
"""

        if current_price == 0:
            price_display = "FREE"
        else:
            price_display = f"${current_price:.2f}"

        book_html += f"""
                <div class="price-info">
                    <div style="margin-bottom: 8px;">
                        <span class="current-price">{price_display}</span>
"""

        if list_price > 0 and list_price != current_price:
            book_html += f"""
                        <span class="list-price">List: ${list_price:.2f}</span>
                        <span class="savings">Save {savings_percent}%</span>
"""

        book_html += """
                    </div>
"""

        if previous_price is not None and previous_price > 0:
            book_html += f"""
                    <div style="font-size: 13px; color: #888; margin-top: 4px;">
                        <span class="previous-price">Last seen: ${previous_price:.2f}</span>
"""
            if price_drop and price_drop > 0:
                book_html += f"""
                        <span class="price-drop">↓ ${price_drop:.2f} ({price_drop_percent}%)</span>
"""
            book_html += """
                    </div>
"""

        book_html += f"""
                </div>
                <a href="{amazon_link}" class="buy-button">Buy now on Amazon</a>
            </div>
        </div>
    </div>
"""
        return book_html

    @staticmethod
    def generate_email_html(books: List[Dict[str, Any]],
                            recommended_deals: List[Dict[str, Any]] = None) -> str:
        """
        Generate HTML email content from book data.

        Args:
            books: List of tracked deal dictionaries (sample books + daily deal matches)
            recommended_deals: Optional list of recommended deal dictionaries.
                If provided, email uses two-section layout.
                If None, email uses flat layout (backward compatible).

        Returns:
            HTML string for email body
        """
        # CSS styles (same as before)
        html = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #ff9900;
            border-bottom: 2px solid #ff9900;
            padding-bottom: 10px;
            font-size: 24px;
            margin-bottom: 5px;
        }
        h2 {
            color: #232f3e;
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #e0e0e0;
        }
        .no-deals {
            color: #888;
            font-style: italic;
            padding: 16px 0;
        }
        .book {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin: 16px 0;
            background-color: #ffffff;
        }
        .book-content {
            display: table;
            width: 100%;
        }
        .book-cover {
            display: table-cell;
            vertical-align: top;
            width: 120px;
            padding-right: 20px;
        }
        .book-cover img {
            max-width: 120px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.12);
        }
        .book-details {
            display: table-cell;
            vertical-align: top;
        }
        .book-title {
            font-size: 18px;
            font-weight: bold;
            color: #232f3e;
            margin: 0 0 4px 0;
            line-height: 1.3;
        }
        .book-author {
            font-size: 14px;
            color: #555;
            margin: 0 0 10px 0;
        }
        .price-info {
            margin: 10px 0;
        }
        .current-price {
            font-size: 22px;
            font-weight: bold;
            color: #b12704;
        }
        .list-price {
            font-size: 14px;
            color: #888;
            text-decoration: line-through;
            margin-left: 8px;
        }
        .savings {
            display: inline-block;
            background-color: #c45500;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }
        .previous-price {
            font-size: 13px;
            color: #888;
        }
        .price-drop {
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }
        .buy-button {
            display: inline-block;
            background-color: #ff9900;
            color: #ffffff;
            padding: 10px 24px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            margin-top: 12px;
            letter-spacing: 0.3px;
        }
        .buy-button:hover {
            background-color: #ec8a00;
        }
        .buy-button:active {
            color: #ffffff;
        }
        .match-reason {
            font-size: 13px;
            color: #067d62;
            margin: 6px 0 10px 0;
            font-weight: 600;
            padding: 4px 0;
        }
        .match-reason::before {
            content: "\\2713  ";
            font-weight: bold;
        }
    </style>
</head>
<body>
    <h1>Kindle Deals Alert</h1>
"""

        use_sections = recommended_deals is not None

        if use_sections:
            # Two-section layout
            html += """
    <h2>Tracked Deals</h2>
"""
            if books:
                for book in books:
                    html += EmailNotifier._generate_book_html(book)
            else:
                html += """
    <p class="no-deals">No tracked deals today</p>
"""

            if recommended_deals:
                html += """
    <h2>Recommended Deals</h2>
"""
                for book in recommended_deals:
                    html += EmailNotifier._generate_book_html(book)
        else:
            # Flat layout (backward compatible)
            html += """
    <p style="color: #555; margin-top: 5px;">The following Kindle books on your watchlist are now on sale:</p>
"""
            for book in books:
                html += EmailNotifier._generate_book_html(book)

        html += """
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #e0e0e0;">
    <p style="font-size: 11px; color: #999; text-align: center;">
        Kindle Deals Monitor &middot; Automated notification
    </p>
</body>
</html>
"""
        return html
```

**Step 4: Run new email tests**

Run: `pytest tests/test_email_notifier.py -v`
Expected: All tests PASS (both new and existing)

**Step 5: Commit**

```bash
git add src/email_notifier.py tests/test_email_notifier.py
git commit -m "feat(email): add two-section layout for tracked and recommended deals"
```

---

### Task 4: Phase 3 - Parallel Recommendation Checking

**Files:**
- Modify: `src/check_deals.py` (add imports, new function, integrate into `check_deals()`)

**Step 1: Add imports**

At the top of `src/check_deals.py` (after line 9), add:

```python
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
```

**Step 2: Write the `check_recommendations_phase` function**

Add after the `check_daily_deals_phase` function (after line 361):

```python
def check_recommendations_phase(scraper, db: Database, check_delay: int,
                                 concurrency: int = 3, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Check prices for all recommended books using parallel Playwright tabs.

    Creates a pool of browser pages and uses ThreadPoolExecutor to scrape
    book info concurrently. DB operations happen in the main thread.

    Args:
        scraper: AmazonScraper instance (already opened)
        db: Database instance
        check_delay: Delay between checks in milliseconds
        concurrency: Number of parallel browser tabs
        dry_run: If True, don't update database

    Returns:
        List of deal dicts for recommended books that qualify
    """
    rec_asins = db.get_unchecked_recommendation_asins()
    if not rec_asins:
        logger.info("No unchecked recommendation ASINs to process")
        return []

    logger.info(f"Checking {len(rec_asins)} recommended books with {concurrency} parallel tabs...")

    # Create page pool
    page_pool = queue.Queue()
    created_pages = []
    for _ in range(concurrency):
        p = scraper.new_page()
        page_pool.put(p)
        created_pages.append(p)

    def scrape_worker(asin: str):
        """Worker that grabs a page from pool, scrapes, returns page."""
        page = page_pool.get()
        try:
            result = scrape_book_info(page, asin)
            time.sleep(check_delay / 1000)
            return (asin, result)
        except Exception as e:
            logger.error(f"Worker error for {asin}: {e}")
            return (asin, None)
        finally:
            page_pool.put(page)

    deals_found = []
    checked_count = 0
    error_count = 0

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(scrape_worker, asin): asin for asin in rec_asins}

            for future in as_completed(futures):
                asin = futures[future]
                try:
                    asin, book_info = future.result()
                except Exception as e:
                    logger.error(f"Future error for {asin}: {e}")
                    error_count += 1
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                checked_count += 1
                if checked_count % 50 == 0:
                    logger.info(f"Progress: {checked_count}/{len(rec_asins)} recommendations checked")

                if not book_info or book_info.get('already_owned'):
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                title = book_info.get('title')
                author = book_info.get('author', '')
                cover_url = book_info.get('cover_url')
                current_price = book_info.get('current_price')
                list_price = book_info.get('list_price')

                if not title or current_price is None or list_price is None:
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                # Ensure book exists in DB (for price_history/notifications FK)
                if not dry_run:
                    db.add_recommendation_book(asin, title, author, cover_url)

                # Check deal criteria
                if not is_deal(current_price, list_price):
                    if not dry_run:
                        db.add_deal_check(asin, was_deal=False, notified=False)
                    continue

                # Check notification rules
                previous_price = db.get_previous_price(asin)
                if not dry_run:
                    db.add_price_history(asin, current_price, list_price)

                last_notification = db.get_last_notification(asin)
                last_notified_price = float(last_notification['notified_price']) if last_notification and last_notification['notified_price'] is not None else None

                if should_notify(current_price, list_price, last_notified_price):
                    savings_percent = calculate_savings_percent(current_price, list_price)
                    source_title = db.get_recommendation_source(asin)
                    match_reason = f"Recommended from: {source_title}" if source_title else "Recommended"

                    deals_found.append({
                        'asin': asin,
                        'title': title,
                        'author': author,
                        'cover_url': cover_url,
                        'current_price': current_price,
                        'list_price': list_price,
                        'previous_price': previous_price,
                        'savings_percent': savings_percent,
                        'match_reason': match_reason
                    })

                    if not dry_run:
                        db.add_notification(asin, current_price)

                    logger.info(f"Recommended deal: {title} - ${current_price:.2f} ({match_reason})")

                if not dry_run:
                    db.add_deal_check(asin, was_deal=True if is_deal(current_price, list_price) else False, notified=bool(deals_found and deals_found[-1]['asin'] == asin))

    finally:
        for p in created_pages:
            try:
                p.close()
            except Exception:
                pass

    logger.info(f"Recommendation check complete: {checked_count} checked, {error_count} errors, {len(deals_found)} deals found")
    return deals_found
```

**Step 3: Integrate Phase 3 into `check_deals()`**

In `src/check_deals.py`, modify the `check_deals()` function:

1. Add `skip_recommendations` parameter to the function signature (line 364):

```python
def check_deals(config: Config, db: Database, target_asin: str = None, force: bool = False,
                dry_run: bool = False, skip_samples: bool = False, skip_daily: bool = False,
                skip_recommendations: bool = False):
```

2. Change `deals_found` to `tracked_deals` (line 388):

```python
    tracked_deals = []
```

3. Update all `deals_found.append(deal)` in Phase 1 (line 510) to `tracked_deals.append(deal)`

4. Update Phase 2 (line 534) to `tracked_deals.extend(daily_deals)`

5. Add Phase 3 after Phase 2 (after line 534), and add `recommended_deals` variable:

```python
            # Phase 3: Check recommended book prices
            recommended_deals = []
            if not skip_recommendations and not target_asin:
                concurrency = config.get('deals.recommendation_concurrency', 3)
                recommended_deals = check_recommendations_phase(
                    scraper, db, check_delay, concurrency, dry_run
                )
```

6. Update the email sending section (lines 539-562) to use two lists:

```python
    # Send email if deals found in either section
    all_deals = tracked_deals + recommended_deals
    if all_deals and not dry_run:
        logger.info(f"Sending email for {len(tracked_deals)} tracked + {len(recommended_deals)} recommended deals...")

        notifier = EmailNotifier(
            smtp_server=config.get('email.smtp_server'),
            smtp_port=config.get('email.smtp_port'),
            from_address=config.get('email.from_address'),
            password=config.get_email_password()
        )

        html = EmailNotifier.generate_email_html(tracked_deals, recommended_deals=recommended_deals)
        today = datetime.now().strftime('%Y-%m-%d')
        subject = f"Kindle Deals {today}: {len(all_deals)} book(s) on sale!"
        to_address = config.get('email.to_address')

        notifier.send_email(to_address, subject, html)
        logger.info("Email sent successfully")
    elif all_deals and dry_run:
        logger.info(f"DRY RUN: Would send email for {len(tracked_deals)} tracked + {len(recommended_deals)} recommended deals:")
        for deal in tracked_deals:
            logger.info(f"  [Tracked] {deal['title']} (${deal['current_price']:.2f})")
        for deal in recommended_deals:
            logger.info(f"  [Recommended] {deal['title']} (${deal['current_price']:.2f})")
    else:
        logger.info("No deals found")
```

**Step 4: Update `main()` to pass the new flag**

In `main()` (around line 626), add argument:

```python
    parser.add_argument('--skip-recommendations', action='store_true',
                        help='Skip checking recommended book prices')
```

And update the `check_deals()` call (line 662):

```python
            check_deals(config, db, target_asin=args.asin, force=args.force,
                        dry_run=args.dry_run, skip_samples=args.skip_samples,
                        skip_daily=args.skip_daily, skip_recommendations=args.skip_recommendations)
```

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/check_deals.py
git commit -m "feat: add Phase 3 parallel recommendation price checking"
```

---

### Task 5: Config and CLI Updates

**Files:**
- Modify: `config.yaml.example`
- Modify: `check_all_deals.sh`

**Step 1: Update config.yaml.example**

Add under the `deals` section (after line 27):

```yaml
  recommendation_concurrency: 3  # number of parallel browser tabs for recommendation checking
```

**Step 2: Update check_all_deals.sh**

Add `SKIP_RECOMMENDATIONS` variable (after line 46):

```bash
SKIP_RECOMMENDATIONS=""
```

Add case in the while loop (after the `--skip-collections` case, around line 77):

```bash
        --skip-recommendations)
            SKIP_RECOMMENDATIONS="--skip-recommendations"
            shift
            ;;
```

Add to help text (after the `--skip-collections` line, around line 92):

```bash
            echo "  --skip-recommendations  Skip checking recommended book prices"
```

Update the python check_deals.py call (line 131):

```bash
if python src/check_deals.py $DRY_RUN $VERBOSE $FORCE $SKIP_SAMPLES $SKIP_DAILY $SKIP_RECOMMENDATIONS; then
```

**Step 3: Commit**

```bash
git add config.yaml.example check_all_deals.sh
git commit -m "feat: add --skip-recommendations flag and config option"
```

---

### Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update relevant sections**

Add `--skip-recommendations` to the CLI flags documentation in the Quick Start Commands section and the Scripts section. Update the database schema to include `is_recommendation`. Update the Architecture section to mention Phase 3.

Key additions:
- In `check_all_deals.sh` flags: `--skip-recommendations` - Skip recommended book price checks
- In `check_deals.py` flags: `--skip-recommendations` - Skip checking recommended book prices
- In books table schema: `is_recommendation TINYINT(1) DEFAULT 0`
- In Architecture / check_deals.py description: mention Phase 3 parallel recommendation checking

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with recommended deals feature"
```

---

### Task 7: Final Verification

**Step 1: Run the full test suite**

Run: `pytest -v --tb=short`
Expected: All tests PASS

**Step 2: Verify dry-run works end-to-end**

Run: `python src/check_deals.py --dry-run --verbose --skip-samples --skip-daily`
Expected: Script runs Phase 3 (recommendations) in dry-run mode, prints progress, no DB changes

**Step 3: Verify skip-recommendations flag works**

Run: `python src/check_deals.py --dry-run --verbose --skip-recommendations`
Expected: Script skips Phase 3 entirely

**Step 4: Final commit if any fixes needed**

Only if test failures or issues are found during verification.
