# Sync Library Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign sync_library.py to use the booksAll URL, distinguish owned from sample books, stop early when catching up, and auto-add uncollected samples to a collection.

**Architecture:** Single-pass page processing — each page of 25 items is parsed for ASIN + sample status, checked against DB for early stopping, and batch-processed for collection management. Database schema evolves `is_active` → `is_sample` + `is_deleted`.

**Tech Stack:** Python, MySQL, Playwright, pytest

---

### Task 1: Database schema migration — rename is_active to is_sample

**Files:**
- Modify: `src/database.py:54-77` (table creation + migration)
- Modify: `src/database.py:129-153` (add_book)
- Modify: `src/database.py:189-217` (mark_book_inactive, reactivate_book)
- Modify: `src/database.py:333-343` (get_active_books)
- Modify: `src/database.py:410-417` (get_all_recommended_asins)
- Test: `tests/test_database.py`

**Step 1: Write failing tests for the new schema**

In `tests/test_database.py`, update the existing tests and add new ones:

```python
# Replace test_add_book (line 77-93):
def test_add_book(clean_db):
    """Test adding a sample book to the database."""
    clean_db.add_book(
        asin='B001234567',
        title='Test Book',
        author='Test Author',
        cover_url='https://example.com/cover.jpg'
    )

    book = clean_db.get_book('B001234567')
    assert book is not None
    assert book['asin'] == 'B001234567'
    assert book['title'] == 'Test Book'
    assert book['author'] == 'Test Author'
    assert book['cover_url'] == 'https://example.com/cover.jpg'
    assert book['is_sample'] == 1
    assert book['is_deleted'] == 0
    assert book['date_added'] is not None


def test_add_owned_book(clean_db):
    """Test adding an owned (non-sample) book."""
    clean_db.add_book(
        asin='B001234567',
        title='Test Book',
        is_sample=False
    )

    book = clean_db.get_book('B001234567')
    assert book['is_sample'] == 0
    assert book['is_deleted'] == 0


# Replace test_get_active_books (line 171-180):
def test_get_sample_books(clean_db):
    """Test getting all sample books."""
    clean_db.add_book(asin='B001', title='Sample 1')
    clean_db.add_book(asin='B002', title='Sample 2')
    clean_db.add_book(asin='B003', title='Owned', is_sample=False)

    books = clean_db.get_sample_books()
    assert len(books) == 2
    assert all(book['is_sample'] == 1 for book in books)


# Replace test_get_active_books_empty (line 183-186):
def test_get_sample_books_empty(clean_db):
    """Test getting sample books when database is empty."""
    books = clean_db.get_sample_books()
    assert len(books) == 0


def test_get_sample_books_excludes_deleted(clean_db):
    """Test that deleted books are excluded from sample books."""
    clean_db.add_book(asin='B001', title='Sample 1')
    clean_db.add_book(asin='B002', title='Sample 2')
    clean_db.mark_book_deleted('B002')

    books = clean_db.get_sample_books()
    assert len(books) == 1
    assert books[0]['asin'] == 'B001'


def test_mark_book_deleted(clean_db):
    """Test marking a book as deleted."""
    clean_db.add_book(asin='B001', title='Test Book')
    clean_db.mark_book_deleted('B001')

    book = clean_db.get_book('B001')
    assert book['is_deleted'] == 1


def test_undelete_book(clean_db):
    """Test undeleting a book."""
    clean_db.add_book(asin='B001', title='Test Book')
    clean_db.mark_book_deleted('B001')
    clean_db.undelete_book('B001')

    book = clean_db.get_book('B001')
    assert book['is_deleted'] == 0


def test_update_book_sample_status(clean_db):
    """Test updating a book's sample status (e.g., user bought a sample)."""
    clean_db.add_book(asin='B001', title='Test Book', is_sample=True)
    clean_db.update_book_sample_status('B001', is_sample=False)

    book = clean_db.get_book('B001')
    assert book['is_sample'] == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py -v`
Expected: Multiple failures — `is_sample` column doesn't exist, methods not defined

**Step 3: Implement database changes**

In `src/database.py`:

Update `_create_tables` (line 54-127) — change the books table definition:

```python
# Books table — replace is_active with is_sample + is_deleted
cursor.execute("""
    CREATE TABLE IF NOT EXISTS books (
        asin VARCHAR(20) PRIMARY KEY,
        title VARCHAR(500),
        author VARCHAR(255),
        cover_url VARCHAR(1000),
        date_added DATETIME NOT NULL,
        is_sample TINYINT(1) DEFAULT 1,
        is_deleted TINYINT(1) DEFAULT 0
    )
""")

# Migrate existing table: rename is_active -> is_sample, add is_deleted
try:
    cursor.execute("""
        ALTER TABLE books CHANGE is_active is_sample TINYINT(1) DEFAULT 1
    """)
except Exception:
    pass  # Already migrated or column doesn't exist

try:
    cursor.execute("""
        ALTER TABLE books MODIFY title VARCHAR(500) NULL
    """)
except Exception:
    pass

try:
    cursor.execute("""
        ALTER TABLE books ADD COLUMN is_deleted TINYINT(1) DEFAULT 0
    """)
except Exception:
    pass  # Already exists
```

Update `add_book` (line 129-153):

```python
def add_book(self, asin: str, title: str = None, author: str = None,
             cover_url: str = None, is_sample: bool = True) -> bool:
    """
    Add a new book to the database.

    Args:
        asin: Amazon Standard Identification Number
        title: Book title (optional)
        author: Book author (optional)
        cover_url: URL to book cover image (optional)
        is_sample: Whether this is a sample (True) or owned book (False)

    Returns:
        True if book was newly added, False if already existed
    """
    cursor = self.conn.cursor()
    cursor.execute("""
        INSERT IGNORE INTO books (asin, title, author, cover_url, date_added, is_sample)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (asin, title, author, cover_url, datetime.now(), 1 if is_sample else 0))
    self.conn.commit()

    if cursor.rowcount == 0:
        return False
    return True
```

Replace `mark_book_inactive` (line 189-202) with `mark_book_deleted`:

```python
def mark_book_deleted(self, asin: str) -> None:
    """Mark a book as deleted (no longer in library)."""
    cursor = self.conn.cursor()
    cursor.execute("""
        UPDATE books SET is_deleted = 1 WHERE asin = %s
    """, (asin,))
    self.conn.commit()
```

Replace `reactivate_book` (line 204-217) with `undelete_book`:

```python
def undelete_book(self, asin: str) -> None:
    """Restore a deleted book."""
    cursor = self.conn.cursor()
    cursor.execute("""
        UPDATE books SET is_deleted = 0 WHERE asin = %s
    """, (asin,))
    self.conn.commit()
```

Add new method `update_book_sample_status`:

```python
def update_book_sample_status(self, asin: str, is_sample: bool) -> None:
    """Update whether a book is a sample or owned."""
    cursor = self.conn.cursor()
    cursor.execute("""
        UPDATE books SET is_sample = %s WHERE asin = %s
    """, (1 if is_sample else 0, asin))
    self.conn.commit()
```

Replace `get_active_books` (line 333-343) with `get_sample_books`:

```python
def get_sample_books(self) -> List[Dict[str, Any]]:
    """Get all sample books that are not deleted."""
    cursor = self.conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM books WHERE is_sample = 1 AND is_deleted = 0")
    return cursor.fetchall()
```

Update `get_all_recommended_asins` (line 410-417) — change `is_active` to `is_sample` and `is_deleted`:

```python
cursor.execute("""
    SELECT r.recommended_asin, b.title
    FROM recommendations r
    JOIN books b ON r.source_asin = b.asin
    WHERE b.is_sample = 1 AND b.is_deleted = 0
""")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_database.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "refactor: rename is_active to is_sample, add is_deleted column

Migrate books table schema to better represent owned vs sample books.
- is_sample: 1 for samples (default), 0 for owned books
- is_deleted: 1 for books removed from library
- Rename get_active_books -> get_sample_books
- Rename mark_book_inactive -> mark_book_deleted
- Rename reactivate_book -> undelete_book
- Add update_book_sample_status method"
```

---

### Task 2: Update callers of renamed database methods

**Files:**
- Modify: `src/check_deals.py:385,391-392,401,441`
- Modify: `src/sync_library.py:225,250-254`
- Modify: `src/similarity_matcher.py:30`

**Step 1: Update check_deals.py**

Line 385: change `book['is_active'] == 0` to `book['is_sample'] == 0 or book['is_deleted'] == 1`
Line 391: change `db.get_active_books()` to `db.get_sample_books()`
Line 392: change log message from `get_active_books()` to `get_sample_books()`
Line 401: change `book['is_active'] == 0` to `book['is_sample'] == 0 or book['is_deleted'] == 1`
Line 441: change `db.mark_book_inactive(asin)` to `db.mark_book_deleted(asin)`

**Step 2: Update sync_library.py**

Line 225: change `db.get_active_books()` to `db.get_sample_books()`
Lines 250-254: change `mark_book_inactive` to `mark_book_deleted`

Note: The removal logic at lines 249-255 will be reworked in Task 4 (early stopping), but for now just update the method name.

**Step 3: Update similarity_matcher.py**

Line 30: change `self.db.get_active_books()` to `self.db.get_sample_books()`

**Step 4: Run all tests**

Run: `pytest -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/check_deals.py src/sync_library.py src/similarity_matcher.py
git commit -m "refactor: update callers to use renamed database methods

Replace get_active_books with get_sample_books, mark_book_inactive
with mark_book_deleted across check_deals, sync_library, and
similarity_matcher."
```

---

### Task 3: Add config settings for sync

**Files:**
- Modify: `config.yaml.example`
- Test: Manual — read config and verify new keys work

**Step 1: Add sync section to config.yaml.example**

Add after the `scraping` section:

```yaml
sync:
  collection_name: "Read Me 2026"    # Collection to auto-add uncollected samples to
  early_stop_threshold: 10           # Stop after this many consecutive known ASINs
```

**Step 2: Add sync section to your local config.yaml**

Add the same `sync:` block to the real `config.yaml`.

**Step 3: Commit**

```bash
git add config.yaml.example
git commit -m "feat: add sync config for collection name and early-stop threshold"
```

---

### Task 4: Rewrite sync_library.py — booksAll URL + sample detection + early stopping

**Files:**
- Modify: `src/sync_library.py:92-287` (sync_library function)
- Modify: `src/sync_library.py:290-330` (main function — add --force, --skip-collections flags)

**Step 1: Update the main() function with new CLI flags**

```python
def main():
    parser = argparse.ArgumentParser(description='Sync Kindle library from Amazon')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--login', action='store_true', help='Login mode')
    parser.add_argument('--force', action='store_true',
                        help='Force full sync - disable early stopping, enable removal tracking')
    parser.add_argument('--skip-collections', action='store_true',
                        help='Skip auto-adding uncollected samples to collection')
    parser.add_argument('--headless', type=lambda x: x.lower() == 'true', default=None,
                        help='Override headless mode (true/false)')

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

        headless_override = args.headless
        if args.login and headless_override is None:
            headless_override = False

        sync_library(config, db,
                     dry_run=args.dry_run,
                     login_mode=args.login,
                     headless_override=headless_override,
                     force=args.force,
                     skip_collections=args.skip_collections)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
```

**Step 2: Rewrite sync_library function signature and URL**

Update function signature to accept new params:

```python
def sync_library(config: Config, db: Database, dry_run: bool = False,
                 login_mode: bool = False, headless_override: bool = None,
                 force: bool = False, skip_collections: bool = False):
```

Change the URL from `booksSamples` to `booksAll`:

```python
page.goto("https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc/?pageNumber=1")
```

Also update the pagination URL on line 188:

```python
page.goto(f"https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc/?pageNumber={page_num}")
```

**Step 3: Add sample detection to per-item parsing**

Inside the for loop that iterates `book_divs` (around line 200-216), add sample detection. This requires inspecting the live page to find the right selector for the "Sample" label. The general approach:

```python
for div in book_divs:
    try:
        div_id = div.get_attribute('id')
        if not div_id or not div_id.startswith('content-title-'):
            logger.warning(f"Skipping div without valid id: {div_id}")
            continue

        asin = div_id.replace('content-title-', '')

        # Determine if this is a sample or owned book
        # Look for "Sample" label in the parent/sibling elements
        # The parent container should have a label indicating "Sample"
        parent = div.locator('xpath=ancestor::div[contains(@class, "digital_entity")]').first
        is_sample = False
        if parent.count() > 0:
            sample_label = parent.locator('text=Sample').first
            is_sample = sample_label.count() > 0

        # Check collection count for samples (for collection management)
        collection_count = 0
        if is_sample:
            try:
                collection_text = parent.locator('text=/\\d+ Collection/').first
                if collection_text.count() > 0:
                    text = collection_text.inner_text()
                    match = re.search(r'(\d+)\s+Collection', text)
                    if match:
                        collection_count = int(match.group(1))
            except Exception:
                pass

        items.append({
            'asin': asin,
            'is_sample': is_sample,
            'collection_count': collection_count
        })
        logger.info(f"Found ASIN: {asin} ({'sample' if is_sample else 'owned'})")

    except Exception as e:
        logger.warning(f"Failed to extract ASIN: {e}")
        continue
```

**NOTE:** The exact CSS selectors for "Sample" label, collection count, and checkboxes need to be verified against the live page. During implementation, use Playwright to inspect the actual DOM and adjust selectors. The design doc calls this out — take a screenshot of the page first and identify elements before writing final selectors.

**Step 4: Add early-stop logic**

After parsing each page, check the early-stop condition:

```python
# Early-stop tracking (outside the page loop)
consecutive_known = 0
early_stop_threshold = config.get('sync.early_stop_threshold', 10)
should_stop = False

# Inside the for loop, after each item:
existing_book = db.get_book(asin)
if existing_book:
    consecutive_known += 1
    if not force and consecutive_known >= early_stop_threshold:
        logger.info(f"Early stop: {consecutive_known} consecutive known books found")
        should_stop = True
        break
else:
    consecutive_known = 0

# After processing items on a page:
if should_stop:
    break
```

**Step 5: Update DB save logic for is_sample**

Replace the current save logic with one that handles is_sample and updates existing books:

```python
for item in items:
    asin = item['asin']
    is_sample = item['is_sample']
    synced_asins.add(asin)

    existing = db.get_book(asin)
    if existing:
        # Update sample status if changed (e.g., user bought a sample)
        if existing['is_sample'] != (1 if is_sample else 0):
            logger.info(f"ASIN {asin} status changed: {'sample' if is_sample else 'owned'}")
            if not dry_run:
                db.update_book_sample_status(asin, is_sample)
        skipped_count += 1
    else:
        if not dry_run:
            db.add_book(asin=asin, is_sample=is_sample)
        added_count += 1
```

**Step 6: Condition removal tracking on --force flag**

Only run the "mark deleted" logic when doing a full sync:

```python
# Only mark books as deleted during full (--force) syncs
if force and not dry_run:
    all_sample_books = {book['asin'] for book in db.get_sample_books()}
    removed_asins = all_sample_books - synced_asins
    if removed_asins:
        logger.info(f"Marking {len(removed_asins)} books as deleted")
        for asin in removed_asins:
            db.mark_book_deleted(asin)
```

**Step 7: Run manually to test**

Run: `python src/sync_library.py --dry-run --verbose`
Expected: Should navigate to booksAll page and show items with sample/owned classification

**Step 8: Commit**

```bash
git add src/sync_library.py
git commit -m "feat: switch to booksAll URL with sample detection and early stopping

- Use booksAll/dateDsc URL instead of booksSamples
- Detect Sample label to classify items as sample vs owned
- Track consecutive known ASINs for early-stop optimization
- Add --force flag to disable early stopping and enable removal tracking
- Add --skip-collections flag (collection logic in next commit)"
```

---

### Task 5: Add collection management to sync_library.py

**Files:**
- Modify: `src/sync_library.py` (add collection management function + integrate into sync loop)

**Step 1: Inspect the live page DOM**

Before writing any code, navigate to the booksAll page in non-headless mode and inspect:
1. Checkbox elements for each item — what selector identifies them
2. The "Add to Collections" button — where it is and what enables it
3. The collection picker dialog — how collections are listed and selected

Run: `python src/sync_library.py --login --headless false` (or use the Playwright MCP tool to navigate)

Take screenshots and note exact selectors.

**Step 2: Write the collection management function**

```python
def add_samples_to_collection(page, items: list, collection_name: str, dry_run: bool = False) -> int:
    """
    Add uncollected samples on the current page to a collection.

    Args:
        page: Playwright page object
        items: List of item dicts with 'asin', 'is_sample', 'collection_count'
        collection_name: Name of the collection to add to
        dry_run: If True, don't actually make changes

    Returns:
        Number of samples added to collection
    """
    # Find samples with 0 collections
    uncollected = [item for item in items if item['is_sample'] and item['collection_count'] == 0]

    if not uncollected:
        return 0

    logger.info(f"Found {len(uncollected)} uncollected samples on this page")

    if dry_run:
        for item in uncollected:
            logger.info(f"  DRY RUN: Would add {item['asin']} to '{collection_name}'")
        return len(uncollected)

    try:
        # Check the checkbox for each uncollected sample
        for item in uncollected:
            # NOTE: Adjust selector based on live page inspection
            checkbox = page.locator(f'input[type="checkbox"][value="{item["asin"]}"]').first
            if checkbox.count() > 0:
                checkbox.check()
                logger.debug(f"Checked box for {item['asin']}")
            else:
                logger.warning(f"Could not find checkbox for {item['asin']}")

        # Click "Add to Collections" button
        # NOTE: Adjust selector based on live page inspection
        add_btn = page.locator('button:has-text("Add to Collections"), a:has-text("Add to Collections")').first
        if add_btn.count() == 0:
            logger.warning("Could not find 'Add to Collections' button")
            return 0

        add_btn.click()
        page.wait_for_timeout(1000)

        # Select the target collection from the dialog
        # NOTE: Adjust selector based on live page inspection
        collection_option = page.locator(f'text="{collection_name}"').first
        if collection_option.count() == 0:
            # Log available collections for debugging
            logger.error(f"Collection '{collection_name}' not found in picker")
            # Try to close the dialog
            page.keyboard.press('Escape')
            return 0

        collection_option.click()
        page.wait_for_timeout(500)

        # Confirm/submit
        # NOTE: Adjust selector based on live page inspection
        confirm_btn = page.locator('button:has-text("Add"), button:has-text("Done"), button:has-text("Save")').first
        if confirm_btn.count() > 0:
            confirm_btn.click()
            page.wait_for_timeout(1000)

        logger.info(f"Added {len(uncollected)} samples to '{collection_name}'")
        return len(uncollected)

    except Exception as e:
        logger.warning(f"Failed to add samples to collection: {e}")
        # Try to uncheck everything to clean up
        try:
            page.keyboard.press('Escape')
        except Exception:
            pass
        return 0
```

**Step 3: Integrate into sync loop**

After parsing items on each page but before moving to the next page, call the collection management function:

```python
# Collection management (after item parsing, before next page)
if not skip_collections and not dry_run:
    collection_name = config.get('sync.collection_name', 'Read Me 2026')
    added = add_samples_to_collection(page, page_items, collection_name, dry_run)
    if added > 0:
        total_collections_added += added
elif not skip_collections and dry_run:
    collection_name = config.get('sync.collection_name', 'Read Me 2026')
    add_samples_to_collection(page, page_items, collection_name, dry_run=True)
```

**Step 4: Test manually**

Run: `python src/sync_library.py --dry-run --verbose`
Expected: Should log uncollected samples it would add to the collection

Then test for real (non-dry-run) on a single page to verify the DOM interaction works.

**Step 5: Commit**

```bash
git add src/sync_library.py
git commit -m "feat: auto-add uncollected samples to configured collection

Batch-select samples with 0 collections on each page and add them
to the configured sync.collection_name. Skippable with --skip-collections."
```

---

### Task 6: Update check_all_deals.sh

**Files:**
- Modify: `check_all_deals.sh`

**Step 1: Forward --force to sync_library and add --skip-collections**

Add `SKIP_COLLECTIONS` variable parsing:

```bash
SKIP_COLLECTIONS=""

# In the while loop, add:
--skip-collections)
    SKIP_COLLECTIONS="--skip-collections"
    shift
    ;;
```

Update the help text to mention `--skip-collections`.

Forward `--force` to the sync step:

```bash
if python src/sync_library.py $VERBOSE $LOGIN $FORCE $SKIP_COLLECTIONS; then
```

**Step 2: Commit**

```bash
git add check_all_deals.sh
git commit -m "feat: pass --force and --skip-collections through to sync_library"
```

---

### Task 7: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update database schema section**

Replace the `books` table schema with:

```sql
CREATE TABLE books (
    asin VARCHAR(20) PRIMARY KEY,
    title VARCHAR(500),
    author VARCHAR(255),
    cover_url VARCHAR(1000),
    date_added DATETIME NOT NULL,
    is_sample TINYINT(1) DEFAULT 1,
    is_deleted TINYINT(1) DEFAULT 0
)
```

**Step 2: Update CLI flags section**

Add `--force` and `--skip-collections` to sync_library.py docs.
Add `--skip-collections` to check_all_deals.sh docs.

**Step 3: Update config section**

Add `sync` section to the configuration docs.

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for sync library redesign"
```

---

### Task 8: DOM inspection and selector refinement

**Files:**
- Modify: `src/sync_library.py` (adjust selectors based on live page)

This is a manual task. Use the Playwright MCP browser tools or run sync_library in non-headless mode to:

1. Navigate to `https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc/`
2. Take screenshots / inspect DOM for:
   - How "Sample" is labeled (CSS class? Text node? Badge?)
   - Where collection count appears
   - Checkbox input elements
   - "Add to Collections" button
   - Collection picker dialog structure
3. Update selectors in `sync_library.py` to match actual DOM
4. Test end-to-end with real data

**Step 1: Inspect and adjust selectors**

Use browser dev tools or Playwright snapshot to identify correct selectors.

**Step 2: Test with real data**

Run: `python src/sync_library.py --verbose` (no --dry-run, with real Amazon session)
Verify: Books classified correctly, early stop works, collections assigned.

**Step 3: Commit final selector adjustments**

```bash
git add src/sync_library.py
git commit -m "fix: finalize DOM selectors from live page inspection"
```
