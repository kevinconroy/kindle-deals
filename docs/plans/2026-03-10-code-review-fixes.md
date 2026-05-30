# Code Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 22 issues identified in the expert code review across correctness, resilience, performance, and scraping robustness.

**Architecture:** Changes are grouped into 5 logical layers applied bottom-up: (1) database foundation fixes, (2) correctness bugs, (3) resilience/error handling, (4) performance, (5) scraping divergence. Each layer builds on the previous without breaking existing tests.

**Tech Stack:** Python 3.x, mysql-connector-python, Playwright (sync + async), pytest, asyncio

---

## Task 1: Fix cursor leaks in Database — every method must close its cursor

**Files:**
- Modify: `src/database.py` (all methods)
- Test: `tests/test_database.py`

The entire `Database` class creates cursors without ever calling `cursor.close()`. With `mysql-connector-python`, an unclosed cursor that has unread results causes `InternalError: Unread result found` on the next query. Every method must use a `try/finally` or context manager.

**Step 1: Verify the failing pattern exists**

Run: `grep -n "cursor = self.conn.cursor" src/database.py`
Expected: ~15 lines showing cursors assigned but never closed.

**Step 2: Rewrite every method in `database.py` to close cursors**

Replace every method body that creates a cursor with a `try/finally` pattern. Here is the complete rewrite of each method — apply these changes to `src/database.py`:

`_create_tables` — wrap entire body:
```python
def _create_tables(self):
    cursor = self.conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS books (...)""")
        # ... all existing DDL and migration statements unchanged ...
        self.conn.commit()
    finally:
        cursor.close()
```

`add_book`:
```python
def add_book(self, asin, title=None, author=None, cover_url=None, is_sample=True):
    cursor = self.conn.cursor()
    try:
        cursor.execute("""INSERT IGNORE INTO books ...""", (...))
        self.conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
```

Apply the same `try/finally: cursor.close()` pattern to every other method:
`get_book`, `update_book_metadata`, `mark_book_deleted`, `undelete_book`,
`update_book_sample_status`, `add_price_history`, `get_latest_price`,
`get_previous_price`, `was_checked_today`, `add_notification`,
`get_last_notification`, `get_sample_books`, `set_has_owned_copy`,
`get_samples_with_owned_copies`, `add_recommendation`, `get_recommendations`,
`has_recommendations`, `get_all_recommended_asins`, `add_deal_check`,
`was_deal_checked_today`, `get_unchecked_recommendation_asins`,
`add_recommendation_book`, `get_recommendation_source`.

**Step 3: Run existing tests**

```bash
cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && pytest tests/test_database.py -v
```
Expected: All tests pass (no behavior change, only resource management).

**Step 4: Commit**

```bash
git add src/database.py
git commit -m "fix: close all database cursors in try/finally to prevent InternalError: Unread result"
```

---

## Task 2: Add missing indexes to `price_history` table

**Files:**
- Modify: `src/database.py` (price_history DDL in `_create_tables`)
- Test: `tests/test_database.py`

`was_checked_today` and `get_previous_price` both query `price_history WHERE asin = %s` with no index. As history grows over months these become full table scans per book per run.

**Step 1: Add indexes to the price_history DDL**

In `_create_tables`, replace the price_history CREATE TABLE with:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        asin VARCHAR(20) NOT NULL,
        price DECIMAL(10,2),
        list_price DECIMAL(10,2),
        check_date DATETIME NOT NULL,
        FOREIGN KEY (asin) REFERENCES books(asin),
        INDEX idx_price_history_asin_date (asin, check_date),
        INDEX idx_price_history_asin_id (asin, id)
    )
""")
```

Also add a migration block (after the existing migration blocks) to add these indexes to existing tables:

```python
# Migrate: add performance indexes (for existing databases)
try:
    cursor.execute("""
        SELECT INDEX_NAME FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'price_history'
        AND INDEX_NAME = 'idx_price_history_asin_date'
    """, (self.database,))
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE price_history ADD INDEX idx_price_history_asin_date (asin, check_date)")
        cursor.execute("ALTER TABLE price_history ADD INDEX idx_price_history_asin_id (asin, id)")
        self.conn.commit()
except Exception:
    pass
```

**Step 2: Run tests**

```bash
pytest tests/test_database.py -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/database.py
git commit -m "perf: add indexes on price_history(asin, check_date) and (asin, id) to prevent full table scans"
```

---

## Task 3: Add DB reconnect support and bulk query methods

**Files:**
- Modify: `src/database.py`
- Test: `tests/test_database.py`

Three sub-fixes in one task: (a) add `ping_reconnect()` for connection health, (b) add `get_checked_today_asins(deal_day)` bulk method to replace N+1 `was_checked_today` calls, (c) add `get_bulk_previous_prices(asins)` and `get_bulk_last_notifications(asins)` for Phase 1/3 N+1 fixes.

**Step 1: Write new tests**

Add to `tests/test_database.py`:

```python
def test_get_checked_today_asins(clean_db):
    """Test bulk fetch of ASINs already checked today."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_deal_check('B001', was_deal=True, notified=True)

    from datetime import datetime
    deal_day = datetime.combine(datetime.now().date(), datetime.min.time())
    checked = clean_db.get_checked_today_asins(deal_day)
    assert 'B001' in checked
    assert 'B002' not in checked


def test_get_bulk_previous_prices(clean_db):
    """Test bulk fetch of previous prices for multiple ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_price_history('B001', 9.99, 19.99)
    clean_db.add_price_history('B001', 7.99, 19.99)
    clean_db.add_price_history('B002', 3.99, 14.99)

    prices = clean_db.get_bulk_previous_prices(['B001', 'B002', 'B003'])
    assert prices['B001'] == 7.99
    assert prices['B002'] == 3.99
    assert 'B003' not in prices


def test_get_bulk_last_notifications(clean_db):
    """Test bulk fetch of last notification prices for multiple ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_notification('B001', 9.99)
    clean_db.add_notification('B001', 7.99)
    clean_db.add_notification('B002', 3.99)

    notifications = clean_db.get_bulk_last_notifications(['B001', 'B002', 'B003'])
    assert notifications['B001'] == 7.99
    assert notifications['B002'] == 3.99
    assert 'B003' not in notifications


def test_get_existing_asins(clean_db):
    """Test bulk fetch of known ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')

    known = clean_db.get_existing_asins(['B001', 'B002', 'B999'])
    assert 'B001' in known
    assert 'B002' in known
    assert 'B999' not in known
```

**Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_database.py::test_get_checked_today_asins tests/test_database.py::test_get_bulk_previous_prices tests/test_database.py::test_get_bulk_last_notifications tests/test_database.py::test_get_existing_asins -v
```
Expected: AttributeError — methods don't exist yet.

**Step 3: Add the new methods to `Database` in `src/database.py`**

Add after `was_checked_today`:

```python
def get_checked_today_asins(self, deal_day: datetime) -> set:
    """
    Bulk-fetch all ASINs that already have a price_history entry since deal_day.
    Replaces per-book was_checked_today() calls in Phase 1.
    """
    cursor = self.conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT asin FROM price_history WHERE check_date >= %s
        """, (deal_day,))
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()

def get_bulk_previous_prices(self, asins: list) -> dict:
    """
    Fetch the most recent price for each ASIN in one query.
    Returns dict mapping asin -> float price (only ASINs with history).
    """
    if not asins:
        return {}
    placeholders = ','.join(['%s'] * len(asins))
    cursor = self.conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT ph.asin, ph.price
            FROM price_history ph
            INNER JOIN (
                SELECT asin, MAX(id) AS max_id
                FROM price_history
                WHERE asin IN ({placeholders})
                GROUP BY asin
            ) latest ON ph.asin = latest.asin AND ph.id = latest.max_id
        """, asins)
        return {
            row['asin']: float(row['price'])
            for row in cursor.fetchall()
            if row['price'] is not None
        }
    finally:
        cursor.close()

def get_bulk_last_notifications(self, asins: list) -> dict:
    """
    Fetch the most recent notified_price for each ASIN in one query.
    Returns dict mapping asin -> float price (only ASINs with notifications).
    """
    if not asins:
        return {}
    placeholders = ','.join(['%s'] * len(asins))
    cursor = self.conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT n.asin, n.notified_price
            FROM notifications n
            INNER JOIN (
                SELECT asin, MAX(id) AS max_id
                FROM notifications
                WHERE asin IN ({placeholders})
                GROUP BY asin
            ) latest ON n.asin = latest.asin AND n.id = latest.max_id
        """, asins)
        return {
            row['asin']: float(row['notified_price'])
            for row in cursor.fetchall()
            if row['notified_price'] is not None
        }
    finally:
        cursor.close()

def get_existing_asins(self, asins: list) -> set:
    """
    Bulk check which ASINs already exist in the books table.
    Replaces per-book get_book() calls in sync_library.
    """
    if not asins:
        return set()
    placeholders = ','.join(['%s'] * len(asins))
    cursor = self.conn.cursor()
    try:
        cursor.execute(f"SELECT asin FROM books WHERE asin IN ({placeholders})", asins)
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()

def get_asins_with_recommendations(self) -> set:
    """
    Return set of source ASINs that already have recommendations stored.
    Replaces per-book has_recommendations() calls in sync_library.
    """
    cursor = self.conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT source_asin FROM recommendations")
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()

def add_recommendations_bulk(self, rows: list) -> None:
    """
    Bulk-insert recommendation rows. Each row is (source_asin, recommended_asin).
    Silently ignores duplicates.
    """
    if not rows:
        return
    cursor = self.conn.cursor()
    try:
        now = datetime.now()
        cursor.executemany("""
            INSERT IGNORE INTO recommendations (source_asin, recommended_asin, created_date)
            VALUES (%s, %s, %s)
        """, [(src, rec, now) for src, rec in rows])
        self.conn.commit()
    finally:
        cursor.close()

def ping_reconnect(self) -> None:
    """Ping the MySQL connection and reconnect if dropped."""
    try:
        self.conn.ping(reconnect=True, attempts=3, delay=2)
    except Exception as e:
        logger = __import__('logging').getLogger(__name__)
        logger.warning(f"DB reconnect attempt failed: {e}")
```

**Step 4: Run tests**

```bash
pytest tests/test_database.py -v
```
Expected: All tests pass including the 4 new ones.

**Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat: add bulk DB query methods and ping_reconnect to eliminate N+1 queries"
```

---

## Task 4: Fix correctness bug — daily deals phase must call `should_notify`

**Files:**
- Modify: `src/check_deals.py` (`check_daily_deals_phase`)
- Test: `tests/test_deal_logic.py` (add integration-style test with mocks)

Phase 2 appends every matched daily deal to `deals_found` without consulting `should_notify` or `get_last_notification`. A book emailed yesterday at $2.99 will be emailed again today at $2.99, violating the notification rules.

**Step 1: Write failing test**

Add to `tests/test_deal_logic.py`:

```python
def test_should_notify_rejects_same_price():
    """should_notify must return False if price hasn't dropped below previous notification."""
    from src.deal_logic import should_notify
    # Already notified at $2.99, still $2.99 → do not notify again
    assert should_notify(2.99, 14.99, last_notified_price=2.99) is False

def test_should_notify_accepts_lower_price():
    """should_notify must return True if price dropped further."""
    from src.deal_logic import should_notify
    assert should_notify(1.99, 14.99, last_notified_price=2.99) is True
```

**Step 2: Run to verify pass (these test existing logic, should already pass)**

```bash
pytest tests/test_deal_logic.py -v
```
Expected: Both pass — the logic is correct, the bug is that Phase 2 doesn't call it.

**Step 3: Fix `check_daily_deals_phase` in `src/check_deals.py`**

In `check_daily_deals_phase`, after the `is_deal` check (line ~335) and before appending to `deals_found`, add the notification check. Replace:

```python
# existing code around line 335-358:
if not is_deal(current_price, list_price):
    logger.info(f"Match but not a deal: {title} (${current_price})")
    if not dry_run:
        db.add_deal_check(asin, was_deal=False, notified=False)
    continue

savings_percent = calculate_savings_percent(current_price, list_price)
previous_price = db.get_previous_price(asin) if db.get_book(asin) else None
logger.info(f"Daily deal match: {title} - ${current_price:.2f} ({match_reason})")

deals_found.append({...})

if not dry_run:
    db.add_deal_check(asin, was_deal=True, notified=True)
```

With:

```python
if not is_deal(current_price, list_price):
    logger.info(f"Match but not a deal: {title} (${current_price})")
    if not dry_run:
        db.add_deal_check(asin, was_deal=False, notified=False)
    continue

# Check notification rules — same as Phase 1, do not re-notify at same/higher price
last_notification = db.get_last_notification(asin)
last_notified_price = (
    float(last_notification['notified_price'])
    if last_notification and last_notification['notified_price'] is not None
    else None
)
if not should_notify(current_price, list_price, last_notified_price):
    logger.debug(f"Skipping {title} - already notified at same/lower price")
    if not dry_run:
        db.add_deal_check(asin, was_deal=True, notified=False)
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
    db.add_notification(asin, current_price)
    db.add_deal_check(asin, was_deal=True, notified=True)
```

**Step 4: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 5: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: daily deals phase now calls should_notify to prevent duplicate notifications"
```

---

## Task 5: Fix correctness bug — `notified` flag in Phase 3 uses stale `deals_found[-1]`

**Files:**
- Modify: `src/check_deals.py` (`check_recommendations_phase`)

Lines 643-645 in Phase 3:
```python
notified = bool(deals_found and deals_found[-1]['asin'] == asin)
```
This checks whether the *last appended deal* is the current book — which is wrong when two consecutive books are both deals. Use a local boolean instead.

**Step 1: Fix `check_recommendations_phase` in `src/check_deals.py`**

Replace lines 610-645 (from `if should_notify(...)` to end of the per-ASIN block):

```python
        notified_flag = False
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

            notified_flag = True
            logger.info(f"Recommended deal: {title} - ${current_price:.2f} ({match_reason})")

        if not dry_run:
            was_deal = is_deal(current_price, list_price)
            db.add_deal_check(asin, was_deal=was_deal, notified=notified_flag)
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: use local notified_flag in Phase 3 instead of stale deals_found[-1] check"
```

---

## Task 6: Fix correctness bug — use `amazon.domain` config for all URLs

**Files:**
- Modify: `src/check_deals.py`
- Modify: `src/sync_library.py`

All scraping URLs are hardcoded to `www.amazon.com`. The config has `amazon.domain` but it is never read.

**Step 1: Thread domain through `check_deals.py`**

In `check_deals` function, after reading `session_path`, add:
```python
amazon_domain = config.get('amazon.domain', 'amazon.com')
```

Pass `amazon_domain` as a parameter to `scrape_book_info`, `scrape_daily_deals`, and `check_daily_deals_phase`. Update each function signature to accept `domain: str = 'amazon.com'` and replace every `https://www.amazon.com` with `f"https://www.{domain}"`.

Specifically:

`scrape_book_info(page, asin, domain='amazon.com')`:
```python
url = f"https://www.{domain}/dp/{asin}"
```

`scrape_daily_deals(page, domain='amazon.com')`:
```python
deals_url = f"https://www.{domain}/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D"
```

`_async_scrape_book_info(page, asin, domain='amazon.com')`:
```python
url = f"https://www.{domain}/dp/{asin}"
```

`_async_scrape_recommendations(session_path, headless, page_timeout, rec_asins, check_delay, concurrency, domain='amazon.com')`:
- Add `domain` param, pass through to `_async_scrape_book_info`.

`check_recommendations_phase(...)`:
- Add `domain: str = 'amazon.com'` param, pass through to `_async_scrape_recommendations`.

In `check_deals` function, pass `domain=amazon_domain` to all these call sites.

**Step 2: Thread domain through `sync_library.py`**

In `sync_library` function, after reading `session_path`, add:
```python
amazon_domain = config.get('amazon.domain', 'amazon.com')
```

Replace all hardcoded `https://www.amazon.com` occurrences with `f"https://www.{amazon_domain}"`:
- Line 200: `page.goto(f"https://www.{amazon_domain}/hz/mycd/...")`
- Line 221: same pattern
- Line 281: same pattern
- Line 451: same pattern (cleanup URL)

In `scrape_recommendations(page, asin)` — add `domain='amazon.com'` parameter and update line 42.

Pass `domain=amazon_domain` to `scrape_recommendations` calls at line 491.

**Step 3: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 4: Commit**

```bash
git add src/check_deals.py src/sync_library.py
git commit -m "fix: use amazon.domain config for all URLs instead of hardcoded amazon.com"
```

---

## Task 7: Fix correctness bug — DST-aware Eastern Time offset

**Files:**
- Modify: `src/check_deals.py` (`get_current_deal_day`)
- Test: `tests/test_deal_logic.py`

The fixed `timedelta(hours=-5)` is wrong March–November when Eastern is UTC-4 (EDT). Use the `zoneinfo` stdlib module (Python 3.9+) to get the correct offset.

**Step 1: Write a test**

Add to `tests/test_deal_logic.py`:

```python
def test_get_current_deal_day_returns_date():
    """get_current_deal_day should return a datetime at midnight."""
    from src.check_deals import get_current_deal_day
    from datetime import datetime, time
    result = get_current_deal_day()
    assert isinstance(result, datetime)
    assert result.time() == time(0, 0, 0)
```

**Step 2: Run to verify it currently passes (basic shape test)**

```bash
pytest tests/test_deal_logic.py::test_get_current_deal_day_returns_date -v
```

**Step 3: Replace the fixed offset with `zoneinfo`**

In `src/check_deals.py`, replace `get_current_deal_day`:

```python
def get_current_deal_day() -> datetime:
    """
    Get the current "deal day" considering 3 AM Eastern reset time.

    Deals reset at 3 AM Eastern. Uses zoneinfo for correct DST handling.
    Returns midnight of the current deal day.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # Python 3.8 fallback

    now_eastern = datetime.now(ZoneInfo('America/New_York'))

    # If before 3 AM, treat as previous deal day
    if now_eastern.hour < 3:
        deal_day = now_eastern.date() - timedelta(days=1)
    else:
        deal_day = now_eastern.date()

    return datetime.combine(deal_day, datetime.min.time())
```

Remove the `from datetime import timezone` import inside the function (now unused).

**Step 4: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass. (zoneinfo is stdlib in Python 3.9+; if on 3.8, `pip install backports.zoneinfo`.)

**Step 5: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: use zoneinfo for DST-aware Eastern Time in get_current_deal_day (was fixed UTC-5)"
```

---

## Task 8: Resilience — don't save session state after CAPTCHA/auth failure

**Files:**
- Modify: `src/scraper.py` (`AmazonScraper.__exit__`)
- Modify: `src/check_deals.py` (`_async_scrape_recommendations`)

If Amazon serves a login page or CAPTCHA, saving the browser state at that point corrupts the stored session. Only save state when scraping succeeded.

**Step 1: Add `mark_session_valid()` / `invalidate_session()` to `AmazonScraper`**

In `src/scraper.py`, add instance variable and methods:

```python
def __init__(self, session_path, headless=True, page_timeout=30000):
    # ... existing ...
    self._session_valid = True  # assume valid until proven otherwise

def mark_session_invalid(self):
    """Call this when a login page or CAPTCHA is detected."""
    self._session_valid = False

def __exit__(self, exc_type, exc_val, exc_tb):
    if self.context:
        if self._session_valid:
            try:
                self.context.storage_state(path=self.session_path)
            except Exception:
                pass
        else:
            logger.warning("Session was invalidated (CAPTCHA/login detected) — not saving state")
        self.context.close()
    if self.browser:
        self.browser.close()
    if self.playwright:
        self.playwright.stop()
```

**Step 2: Thread session invalidation through `scrape_book_info`**

`scrape_book_info` currently just returns `None` on login/CAPTCHA. It needs a way to signal to the scraper. Add an optional `scraper` param:

```python
def scrape_book_info(page, asin: str, domain: str = 'amazon.com',
                     scraper: 'AmazonScraper' = None) -> Optional[Dict[str, Any]]:
    ...
    if page.locator('input[name="email"]').count() > 0:
        logger.error(f"Hit login page for {asin} - session may have expired")
        if scraper:
            scraper.mark_session_invalid()
        return None
    if page.locator('form[action*="captcha"]').count() > 0:
        logger.error(f"Hit CAPTCHA for {asin} - may need to slow down")
        if scraper:
            scraper.mark_session_invalid()
        return None
```

Pass `scraper=scraper` at all call sites in `check_deals.py` and `sync_library.py`.

**Step 3: Fix async path — only save state if successful**

In `_async_scrape_recommendations`, track whether any scrape succeeded:

```python
# Replace the unconditional storage_state save:
successful = sum(1 for _, info in results if info is not None and not info.get('already_owned'))
if successful > 0:
    await context.storage_state(path=session_path)
else:
    logger.warning("No recommendations scraped successfully — not saving session state")
```

Also add login/CAPTCHA detection to `_async_scrape_book_info` and return a special sentinel `{'session_invalid': True}` that the caller can detect to skip the state save.

**Step 4: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scraper.py src/check_deals.py src/sync_library.py
git commit -m "fix: only save session state when scraping succeeded — prevent CAPTCHA from corrupting stored session"
```

---

## Task 9: Resilience — wrap `scrape_daily_deals` so failures don't abort the run

**Files:**
- Modify: `src/check_deals.py` (`scrape_daily_deals`)

A timeout or network error in `scrape_daily_deals` propagates all the way to `main()`, aborting the run before any tracked-book email is sent.

**Step 1: Wrap the navigation in `scrape_daily_deals`**

```python
def scrape_daily_deals(page, domain: str = 'amazon.com') -> List[str]:
    """Scrape ASINs from Amazon's daily Kindle deals page."""
    deals_url = f"https://www.{domain}/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D"

    logger.info("Navigating to daily deals page...")
    try:
        page.goto(deals_url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(3000)
    except Exception as e:
        logger.error(f"Failed to load daily deals page: {e}")
        return []

    # Check for session expiry
    if page.locator('input[name="email"]').count() > 0:
        logger.error("Hit login page on daily deals — session expired")
        return []
    if page.locator('form[action*="captcha"]').count() > 0:
        logger.error("Hit CAPTCHA on daily deals page")
        return []

    asins = []
    try:
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
    except Exception as e:
        logger.error(f"Error scraping daily deals ASINs: {e}")
        return []

    unique_asins = list(set(asins))
    logger.info(f"Found {len(unique_asins)} unique deal ASINs")
    return unique_asins
```

**Step 2: Add CAPTCHA detection to `scrape_recommendations` in `sync_library.py`**

After the `page.goto` call in `scrape_recommendations`:

```python
page.goto(url, wait_until='domcontentloaded', timeout=15000)
page.wait_for_timeout(2000)

# Check for session expiry or CAPTCHA
if page.locator('input[name="email"]').count() > 0:
    logger.error(f"Hit login page scraping recommendations for {asin}")
    return []
if page.locator('form[action*="captcha"]').count() > 0:
    logger.error(f"Hit CAPTCHA scraping recommendations for {asin}")
    return []
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 4: Commit**

```bash
git add src/check_deals.py src/sync_library.py
git commit -m "fix: wrap scrape_daily_deals in try/except and add CAPTCHA detection to prevent run aborts"
```

---

## Task 10: Resilience — fix async `asyncio.gather` safety

**Files:**
- Modify: `src/check_deals.py` (`_async_scrape_recommendations`)

Two fixes: (a) add `return_exceptions=True` so a `CancelledError` in one task doesn't cancel all tasks, (b) wrap page pool creation and cleanup in `try/finally` so browsers are closed even on exception.

**Step 1: Apply fixes to `_async_scrape_recommendations`**

```python
async def _async_scrape_recommendations(session_path, headless, page_timeout,
                                         rec_asins, check_delay, concurrency, domain='amazon.com'):
    from playwright.async_api import async_playwright

    results = []
    checked_count = 0
    pages = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            storage_state=session_path if os.path.exists(session_path) else None
        )
        context.set_default_timeout(page_timeout)

        page_pool: asyncio.Queue = asyncio.Queue()

        try:
            pages = [await context.new_page() for _ in range(concurrency)]
            for p_obj in pages:
                await page_pool.put(p_obj)

            async def scrape_one(asin: str):
                nonlocal checked_count
                page = await page_pool.get()
                try:
                    logger.debug(f"Scraping recommendation: {asin}")
                    result = await _async_scrape_book_info(page, asin, domain=domain)
                    await asyncio.sleep(check_delay / 1000)
                    checked_count += 1
                    if checked_count % 10 == 0:
                        logger.info(f"Progress: {checked_count}/{len(rec_asins)} recommendations checked")
                    return (asin, result)
                except Exception as e:
                    logger.error(f"Worker error for {asin}: {e}")
                    return (asin, None)
                finally:
                    await page_pool.put(page)

            tasks = [scrape_one(asin) for asin in rec_asins]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any tasks that raised exceptions (e.g., CancelledError)
            results = []
            for asin, raw in zip(rec_asins, raw_results):
                if isinstance(raw, BaseException):
                    logger.error(f"Task for {asin} raised: {raw}")
                    results.append((asin, None))
                else:
                    results.append(raw)

        finally:
            for p_obj in pages:
                try:
                    await p_obj.close()
                except Exception:
                    pass

        # Save session state only if something succeeded
        successful = sum(1 for _, info in results if info is not None)
        if successful > 0:
            await context.storage_state(path=session_path)
        await context.close()
        await browser.close()

    return results
```

Note: `asyncio.gather` returns results in input order when used with a list of tasks, but when `return_exceptions=True` the results list maps 1:1 with `tasks` (not `rec_asins` directly because each task is a coroutine, not the asin). The `scrape_one` coroutine returns `(asin, result)` tuples, so index-based zip with `rec_asins` is wrong. Instead handle it based on the returned tuples:

```python
results = []
for raw in raw_results:
    if isinstance(raw, BaseException):
        logger.error(f"Task raised exception: {raw}")
        # Can't get asin from exception — skip
        continue
    results.append(raw)  # each is (asin, info_or_None)
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: add return_exceptions=True to asyncio.gather and try/finally for browser cleanup"
```

---

## Task 11: Resilience — call `ping_reconnect()` before write-heavy phases

**Files:**
- Modify: `src/check_deals.py`

A long Playwright scraping session can idle the MySQL connection past the server's `wait_timeout`. Add a `ping_reconnect()` call before the DB-write-intensive portion of Phase 1, Phase 2, and Phase 3.

**Step 1: Add `ping_reconnect` calls in `check_deals.py`**

In `check_deals`, just before the `with AmazonScraper(...) as scraper:` block:
```python
db.ping_reconnect()
```

In `check_recommendations_phase`, at the start of the `for asin, book_info in scrape_results:` loop (the post-scrape DB write phase):
```python
db.ping_reconnect()
for asin, book_info in scrape_results:
    ...
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: ping_reconnect before write phases to handle MySQL idle timeout during long scraping runs"
```

---

## Task 12: Performance — eliminate unconditional 2-second waits after page loads

**Files:**
- Modify: `src/check_deals.py` (lines 72, 371)

Both sync `scrape_book_info` and async `_async_scrape_book_info` call `page.wait_for_timeout(2000)` unconditionally after every page load. At 50 books this wastes 100 seconds. The `wait_for(state='visible', timeout=3000)` on the title element already handles dynamic content.

**Step 1: Remove the unconditional waits**

In `scrape_book_info` (sync), remove:
```python
page.wait_for_timeout(2000)
```

In `_async_scrape_book_info` (async), remove:
```python
await page.wait_for_timeout(2000)
```

Both are the lines immediately after `page.goto(...)`. The `wait_for(state='visible')` calls below them are sufficient.

**Step 2: Fix `networkidle` inconsistency in `sync_library.py`**

Line 282 uses `wait_for_load_state('networkidle')` for pages 2+ while page 1 uses `domcontentloaded`. Amazon's digital console never reaches true `networkidle`. Replace:

```python
page.goto(f"https://www.{amazon_domain}/hz/mycd/digital-console/contentlist/booksAll/dateDsc?pageNumber={page_num}")
page.wait_for_load_state('domcontentloaded')
page.wait_for_timeout(2000)  # Allow JS to render content
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 4: Commit**

```bash
git add src/check_deals.py src/sync_library.py
git commit -m "perf: remove unconditional 2s page waits from scraper; fix networkidle→domcontentloaded in sync_library"
```

---

## Task 13: Performance — bulk DB queries in Phase 1 (sample book checks)

**Files:**
- Modify: `src/check_deals.py` (`check_deals` Phase 1 block)

Phase 1 calls `was_checked_today`, `get_previous_price`, and `get_last_notification` per book. Replace with bulk pre-fetch before the loop.

**Step 1: Refactor Phase 1 pre-filtering and per-book DB access**

In `check_deals`, replace the block that builds `books_to_check` and the per-book queries inside the loop:

```python
# --- Phase 1 setup (before the for loop) ---
books = db.get_sample_books()
logger.debug(f"Fetched {len(books)} books from get_sample_books()")

# Bulk fetch already-checked ASINs for today
already_checked = db.get_checked_today_asins(deal_day) if not force else set()

books_to_check = []
skipped_count = 0
inactive_count = 0
for book in books:
    if book['is_sample'] == 0 or book['is_deleted'] == 1:
        inactive_count += 1
        continue
    if not force and book['asin'] in already_checked:
        skipped_count += 1
        continue
    books_to_check.append(book)
books = books_to_check
# ... logging ...

# Bulk fetch previous prices and last notifications for all candidate books
candidate_asins = [b['asin'] for b in books]
bulk_prev_prices = db.get_bulk_previous_prices(candidate_asins)
bulk_last_notifs = db.get_bulk_last_notifications(candidate_asins)

# --- Inside the for book in books loop ---
# Replace:
#   previous_price = db.get_previous_price(asin)
#   last_notification = db.get_last_notification(asin)
#   last_notified_price = float(last_notification['notified_price']) if ...
# With:
previous_price = bulk_prev_prices.get(asin)
last_notified_price = bulk_last_notifs.get(asin)
# (last_notified_price is already a float or None from the bulk method)

if should_notify(current_price, list_price, last_notified_price):
    ...
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "perf: bulk-fetch previous prices and last notifications before Phase 1 loop to eliminate N+1 queries"
```

---

## Task 14: Performance — bulk DB queries in Phase 2 (daily deals)

**Files:**
- Modify: `src/check_deals.py` (`check_daily_deals_phase`)

Phase 2 calls `db.was_deal_checked_today(asin)` per deal ASIN before deciding whether to scrape.

**Step 1: Refactor `check_daily_deals_phase`**

Add a bulk check at the top of the function (after `deal_asins = scrape_daily_deals(...)`:

```python
# Bulk fetch already-checked deal ASINs for today
if not dry_run:
    cursor = db.conn.cursor()
    try:
        cursor.execute("SELECT asin FROM deal_checks WHERE check_date = CURDATE()")
        already_checked_today = {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()
else:
    already_checked_today = set()

for asin in deal_asins:
    if not dry_run and asin in already_checked_today:
        logger.debug(f"Skipping {asin} - already checked today")
        continue
    # ... rest of loop unchanged ...
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "perf: bulk-fetch deal_checks for today before Phase 2 loop to eliminate N+1 was_deal_checked_today calls"
```

---

## Task 15: Performance — bulk DB queries in Phase 3 (recommendations)

**Files:**
- Modify: `src/check_deals.py` (`check_recommendations_phase`)

Phase 3 calls `get_previous_price`, `get_last_notification`, and `get_recommendation_source` per ASIN in the post-scrape processing loop.

**Step 1: Add a bulk `get_bulk_recommendation_sources` method to `database.py`**

```python
def get_bulk_recommendation_sources(self, asins: list) -> dict:
    """
    Fetch source book title for each recommended ASIN in one query.
    Returns dict mapping recommended_asin -> source_book_title.
    """
    if not asins:
        return {}
    placeholders = ','.join(['%s'] * len(asins))
    cursor = self.conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT r.recommended_asin, b.title
            FROM recommendations r
            JOIN books b ON r.source_asin = b.asin
            WHERE r.recommended_asin IN ({placeholders})
            AND b.is_sample = 1 AND b.is_deleted = 0
        """, asins)
        results = {}
        for row in cursor.fetchall():
            # Keep first source title found per ASIN
            if row['recommended_asin'] not in results:
                results[row['recommended_asin']] = row['title']
        return results
    finally:
        cursor.close()
```

**Step 2: Write test**

Add to `tests/test_database.py`:

```python
def test_get_bulk_recommendation_sources(clean_db):
    """Test bulk fetch of recommendation source titles."""
    clean_db.add_book(asin='B001', title='The Way of Kings')
    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B001', 'R002')

    sources = clean_db.get_bulk_recommendation_sources(['R001', 'R002', 'R999'])
    assert sources['R001'] == 'The Way of Kings'
    assert sources['R002'] == 'The Way of Kings'
    assert 'R999' not in sources
```

**Step 3: Refactor `check_recommendations_phase`**

Before the `for asin, book_info in scrape_results:` loop:

```python
result_asins = [asin for asin, _ in scrape_results]
bulk_prev_prices = db.get_bulk_previous_prices(result_asins)
bulk_last_notifs = db.get_bulk_last_notifications(result_asins)
bulk_rec_sources = db.get_bulk_recommendation_sources(result_asins)
```

Inside the loop, replace:
```python
# Remove: previous_price = db.get_previous_price(asin)
# Remove: last_notification = db.get_last_notification(asin); last_notified_price = ...
# Remove: source_title = db.get_recommendation_source(asin)

previous_price = bulk_prev_prices.get(asin)
last_notified_price = bulk_last_notifs.get(asin)
source_title = bulk_rec_sources.get(asin)
```

**Step 4: Run tests**

```bash
pytest tests/test_database.py tests/test_deal_logic.py -v
```
Expected: All pass including the new test.

**Step 5: Commit**

```bash
git add src/check_deals.py src/database.py tests/test_database.py
git commit -m "perf: bulk-fetch previous prices, notifications, and sources before Phase 3 loop to eliminate N+1 queries"
```

---

## Task 16: Performance — bulk queries and bulk inserts in `sync_library.py`

**Files:**
- Modify: `src/sync_library.py`

Two N+1 patterns in `sync_library`: (a) `db.get_book(asin)` called twice per ASIN, (b) `db.has_recommendations(asin)` + individual `db.add_recommendation()` calls.

**Step 1: Replace `get_book` calls with `get_existing_asins` bulk method**

In `sync_library`:

Early-stop loop (line ~331):
```python
# Before the checkpoint loop, collect all ASINs from checkboxes first
# Then do a bulk check:
page_asins = [item['asin'] for item in page_items]
existing_on_page = db.get_existing_asins(page_asins)

for item in page_items:
    asin = item['asin']
    if asin in existing_on_page:
        consecutive_known += 1
        ...
    else:
        consecutive_known = 0
```

Processing loop (line ~403): Replace `existing = db.get_book(asin)` with `existing_asins = db.get_existing_asins([i['asin'] for i in all_items])` before the loop, then `existing = asin in existing_asins`.

Note: where `existing['is_sample']` is accessed, you'll need to keep a `db.get_book(asin)` call for just the dual-state check OR add a `get_books_by_asins(asins)` method. The simplest fix: do the bulk `get_existing_asins` for the skip check, and only call `db.get_book(asin)` for the subset of dual-state candidates (which is a small minority).

**Step 2: Replace `has_recommendations` + individual inserts with bulk methods**

In the recommendation scraping section (lines ~478-499):

```python
# Before the loop:
asins_with_recs = db.get_asins_with_recommendations()

# Accumulate all recommendations
all_rec_rows = []  # list of (source_asin, rec_asin)

for item in all_items:
    asin = item['asin']
    if not item['is_sample']:
        continue
    if asin in asins_with_recs:
        logger.debug(f"Skipping {asin} - already has recommendations")
        continue
    recs = scrape_recommendations(page, asin, domain=amazon_domain)
    for rec_asin in recs:
        all_rec_rows.append((asin, rec_asin))
    page.wait_for_timeout(3000)

# Bulk insert all at once
db.add_recommendations_bulk(all_rec_rows)
logger.info(f"Stored {len(all_rec_rows)} recommendations")
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 4: Commit**

```bash
git add src/sync_library.py src/database.py
git commit -m "perf: bulk-fetch known ASINs and batch-insert recommendations in sync_library to eliminate N+1 queries"
```

---

## Task 17: Performance — batch commits for write methods

**Files:**
- Modify: `src/database.py`
- Modify: `src/check_deals.py`

Each `add_deal_check`, `add_price_history`, and `add_notification` call commits immediately. For Phase 2/3 processing hundreds of ASINs, this is hundreds of individual fsyncs. Add a context-manager-based batch commit mode.

**Step 1: Add `batch_writes()` context manager to `Database`**

```python
from contextlib import contextmanager

@contextmanager
def batch_writes(self):
    """
    Context manager that defers auto-commits inside the block.
    A single commit is issued on successful exit; rollback on exception.

    Usage:
        with db.batch_writes():
            db.add_deal_check(...)
            db.add_price_history(...)
    """
    self._batch_mode = True
    try:
        yield
        self.conn.commit()
    except Exception:
        self.conn.rollback()
        raise
    finally:
        self._batch_mode = False
```

Update `add_deal_check`, `add_price_history`, `add_notification`, and `add_recommendation_book` to skip `self.conn.commit()` when `self._batch_mode` is True:

```python
def add_price_history(self, asin, price, list_price=None):
    cursor = self.conn.cursor()
    try:
        cursor.execute("""INSERT INTO price_history ...""", (...))
        if not getattr(self, '_batch_mode', False):
            self.conn.commit()
    finally:
        cursor.close()
```

Initialize `_batch_mode = False` in `__init__`.

**Step 2: Wrap Phase 1, 2, and 3 write loops in `batch_writes()`**

In `check_deals.py`, Phase 1 per-book writes:
```python
with db.batch_writes():
    db.update_book_metadata(...)
    db.add_price_history(...)
    db.add_notification(...)
```

In Phase 2 at the end of each ASIN's processing:
```python
with db.batch_writes():
    db.add_notification(...)
    db.add_deal_check(...)
```

In Phase 3 post-scrape loop:
```python
with db.batch_writes():
    db.add_recommendation_book(...)
    db.add_price_history(...)
    db.add_notification(...)
    db.add_deal_check(...)
```

**Step 3: Write a test**

Add to `tests/test_database.py`:

```python
def test_batch_writes_commits_atomically(clean_db):
    """batch_writes context manager should commit all writes together."""
    clean_db.add_book(asin='B001', title='Book')
    with clean_db.batch_writes():
        clean_db.add_price_history('B001', 2.99, 14.99)
        clean_db.add_notification('B001', 2.99)
    # Both should be visible
    assert clean_db.get_latest_price('B001') is not None
    assert clean_db.get_last_notification('B001') is not None


def test_batch_writes_rolls_back_on_error(clean_db):
    """batch_writes should rollback if an error occurs mid-batch."""
    import pytest
    clean_db.add_book(asin='B001', title='Book')
    with pytest.raises(Exception):
        with clean_db.batch_writes():
            clean_db.add_price_history('B001', 2.99, 14.99)
            raise RuntimeError("simulated error")
    # Price history should NOT be committed
    assert clean_db.get_latest_price('B001') is None
```

**Step 4: Run tests**

```bash
pytest tests/test_database.py -v
```
Expected: All pass.

**Step 5: Commit**

```bash
git add src/database.py src/check_deals.py tests/test_database.py
git commit -m "perf: add batch_writes() context manager to database to batch commits per phase instead of per row"
```

---

## Task 18: Performance — lightweight scrape before match check in Phase 2

**Files:**
- Modify: `src/check_deals.py`

Currently Phase 2 runs the full `scrape_book_info` (title + author + cover + price + ownership check) for every daily deal ASIN, even though most won't match. Add a fast title+author-only scrape for the match gate.

**Step 1: Add `scrape_book_title_author` function**

```python
def scrape_book_title_author(page, asin: str, domain: str = 'amazon.com') -> Optional[Dict[str, Any]]:
    """
    Lightweight scrape: only fetch title and author for match-gate filtering.
    Used before full scrape_book_info in Phase 2 daily deals.
    """
    try:
        url = f"https://www.{domain}/dp/{asin}"
        page.goto(url, wait_until='domcontentloaded', timeout=15000)

        title = None
        try:
            title_elem = page.locator('#productTitle').first
            title_elem.wait_for(state='visible', timeout=3000)
            title = title_elem.inner_text().strip()
        except Exception:
            pass

        author = None
        for selector in ['.author .contributorNameID', '#bylineInfo .author a.contributorNameID',
                         'span.author a', '#bylineInfo span.author',
                         'a[data-asin] .author', '.contributorNameTrigger']:
            try:
                elem = page.locator(selector).first
                if elem.count() > 0:
                    author = elem.inner_text().strip()
                    break
            except Exception:
                continue

        return {'title': title, 'author': author}
    except Exception as e:
        logger.error(f"Failed lightweight scrape for {asin}: {e}")
        return None
```

**Step 2: Use lightweight scrape for match check in `check_daily_deals_phase`**

Replace the `scrape_book_info(page, asin)` call with:
```python
# Lightweight scrape first — only get title/author for match check
light_info = scrape_book_title_author(page, asin, domain=domain)
if not light_info:
    if not dry_run:
        db.add_deal_check(asin, was_deal=False, notified=False)
    continue

title = light_info.get('title')
author = light_info.get('author', '')
if not title:
    if not dry_run:
        db.add_deal_check(asin, was_deal=False, notified=False)
    continue

is_match, match_reason = matcher.is_match(asin, author, title)
if not is_match:
    logger.debug(f"No match: {title}")
    if not dry_run:
        db.add_deal_check(asin, was_deal=False, notified=False)
    continue

# Only run full scrape for matched books
book_info = scrape_book_info(page, asin, domain=domain)
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 4: Commit**

```bash
git add src/check_deals.py
git commit -m "perf: use lightweight title/author scrape before match check in Phase 2 to skip full scrape for non-matches"
```

---

## Task 19: Fix scraping divergence — sync async `scrape_book_info` parity

**Files:**
- Modify: `src/check_deals.py` (`_async_scrape_book_info`)

The async scraper is missing the `'a[data-asin] .author'` author selector and the `'img[data-a-dynamic-image]'` cover selector present in the sync version. Recommendation emails will have missing author/cover data in cases where Phase 1 succeeds.

**Step 1: Sync the selector lists**

In `_async_scrape_book_info`, update the author selector list:

```python
for selector in ['.author .contributorNameID', '#bylineInfo .author a.contributorNameID',
                 'span.author a', '#bylineInfo span.author',
                 'a[data-asin] .author',          # added: matches sync version
                 '.contributorNameTrigger']:
```

Update the cover selector list:

```python
for selector in ['#ebooksImgBlkFront', '#imgBlkFront', '#ebooksProductImage',
                 '#landingImage', 'img.a-dynamic-image', '#main-image',
                 'img[data-a-dynamic-image]']:    # added: matches sync version
```

Also add CAPTCHA/login detection to the async scraper (currently missing):

```python
if await page.locator('input[name="email"]').count() > 0:
    logger.error(f"Hit login page for {asin} - session may have expired")
    return {'session_invalid': True}
if await page.locator('form[action*="captcha"]').count() > 0:
    logger.error(f"Hit CAPTCHA for {asin}")
    return {'session_invalid': True}
```

In `check_recommendations_phase`, handle `session_invalid` sentinel:
```python
if book_info.get('session_invalid'):
    # Don't record as checked — allow retry tomorrow
    logger.warning(f"Session invalid during recommendation check for {asin} — skipping")
    continue
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: All pass.

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "fix: sync async _async_scrape_book_info selectors with sync version; add CAPTCHA detection to async path"
```

---

## Task 20: Final — run full test suite and verify

**Step 1: Run all tests**

```bash
cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && pytest tests/ -v --tb=short
```
Expected: All tests pass with no failures.

**Step 2: Verify no regressions in key functions**

```bash
# Quick sanity check that imports work and main() parses args
python -c "from src.check_deals import check_deals; print('OK')"
python -c "from src.sync_library import sync_library; print('OK')"
python -c "from src.database import Database; print('OK')"
```

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: verify all 22 code review fixes pass test suite"
```

---

## Summary of All 22 Fixes

| # | Issue | Task |
|---|-------|------|
| 18 | Cursors never closed → InternalError | Task 1 |
| 19 | Missing index on price_history(asin) | Task 2 |
| 21 | DB connection not validated | Task 3 + 11 |
| 3 bulk methods | N+1 groundwork | Task 3 |
| 1 | Daily deals never calls should_notify | Task 4 |
| 2 | notified flag uses stale deals_found[-1] | Task 5 |
| 3 | amazon.domain config never used | Task 6 |
| 4 | Fixed UTC-5 offset ignores DST | Task 7 |
| 5 | Session saved after CAPTCHA | Task 8 |
| 6 | scrape_daily_deals crashes run on timeout | Task 9 |
| 10 | No CAPTCHA detection in scrape_recommendations | Task 9 |
| 7 | asyncio.gather without return_exceptions=True | Task 10 |
| 8 | Session expiry poisons deal_checks | Task 10 + 19 |
| 9 | Browser not closed on exception | Task 10 |
| 11 | Unconditional 2s waits | Task 12 |
| Scraping #6 | networkidle vs domcontentloaded | Task 12 |
| 12 | N+1 queries Phase 1 | Task 13 |
| 14 | N+1 queries sync_library | Task 16 |
| 13 | N+1 queries Phase 3 | Task 15 |
| 15 | Per-row COMMIT | Task 17 |
| 20 | No transaction for multi-step writes | Task 17 |
| 17 | Full page scrape before match check | Task 18 |
| 22 | Sync/async selector divergence | Task 19 |
