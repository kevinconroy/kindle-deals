# Auto-Purchase Eligible Samples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically buy a sampled Kindle book with 1-Click (paying with Amazon Rewards points) when it goes on sale for ≤ $5 and points fully cover the price, and flag it as "Auto-purchased" in the daily email.

**Architecture:** A new isolated `src/purchaser.py` module performs the risky DOM work (parse the points checkbox, tick `#balance-checkbox-0`, click `#one-click-button`, confirm the order). The orchestration logic is unit-tested by monkeypatching the thin DOM helpers, and the pure points-parsing is unit-tested directly. The purchase hook is wired into Phase 1 of `check_deals.py`. A new `purchases` table provides idempotency (written immediately on success); the "stop tracking" update (`mark_book_deleted`) runs after the email send.

**Tech Stack:** Python, Playwright (sync API), MySQL (mysql-connector-python), pytest.

---

### Task 1: `purchases` table + `add_purchase` / `is_purchased`

**Files:**
- Modify: `src/database.py` (add table in `_create_tables`, add two methods)
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_database.py`:

```python
def test_add_and_is_purchased(clean_db):
    """add_purchase records a purchase and is_purchased detects it."""
    clean_db.add_book('B0PURCHASE1', title='Bought Book')
    assert clean_db.is_purchased('B0PURCHASE1') is False

    clean_db.add_purchase('B0PURCHASE1', 3.99, points_applied=3.99)
    assert clean_db.is_purchased('B0PURCHASE1') is True


def test_add_purchase_is_idempotent(clean_db):
    """add_purchase twice for the same asin does not error and stays single."""
    clean_db.add_book('B0PURCHASE2', title='Bought Twice')
    clean_db.add_purchase('B0PURCHASE2', 2.99, points_applied=2.99)
    clean_db.add_purchase('B0PURCHASE2', 2.99, points_applied=2.99)

    cursor = clean_db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM purchases WHERE asin = %s", ('B0PURCHASE2',))
    assert cursor.fetchone()[0] == 1
    cursor.close()
```

Also add `purchases` to the truncate list in the `clean_db` fixture (before `books`):

```python
    cursor.execute("TRUNCATE TABLE purchases")
```

(Place it as the first TRUNCATE, right after `SET FOREIGN_KEY_CHECKS = 0`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_add_and_is_purchased -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'add_purchase'` (or a "table doesn't exist" error once the method is added).

- [ ] **Step 3: Create the table**

In `src/database.py`, inside `_create_tables`, immediately after the `deal_checks` `CREATE TABLE` block (around line 180), add:

```python
            # Purchases table - records auto-purchased books for idempotency/audit
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchases (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    price DECIMAL(10,2) NOT NULL,
                    points_applied DECIMAL(10,2),
                    purchased_date DATETIME NOT NULL,
                    UNIQUE KEY unique_purchase (asin),
                    FOREIGN KEY (asin) REFERENCES books(asin)
                )
            """)
```

- [ ] **Step 4: Add the methods**

In `src/database.py`, add after `get_last_notification` (around line 447):

```python
    def add_purchase(self, asin: str, price: float,
                     points_applied: float = None) -> None:
        """
        Record an auto-purchase. Idempotent: a second call for the same ASIN
        is ignored (UNIQUE constraint on asin).

        Args:
            asin: Amazon Standard Identification Number
            price: Price paid
            points_applied: Dollar value of Rewards points applied (or None)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT IGNORE INTO purchases (asin, price, points_applied, purchased_date)
                VALUES (%s, %s, %s, %s)
            """, (asin, price, points_applied, datetime.now()))
            self.conn.commit()
        finally:
            cursor.close()

    def is_purchased(self, asin: str) -> bool:
        """Return True if this ASIN has already been auto-purchased."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT 1 FROM purchases WHERE asin = %s LIMIT 1", (asin,))
            return cursor.fetchone() is not None
        finally:
            cursor.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_database.py::test_add_and_is_purchased tests/test_database.py::test_add_purchase_is_idempotent -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat(db): add purchases table with add_purchase/is_purchased"
```

---

### Task 2: `purchaser.py` — pure points parsing

**Files:**
- Create: `src/purchaser.py`
- Test: `tests/test_purchaser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_purchaser.py`:

```python
import pytest
from src import purchaser


def test_parse_points_amount_with_decimals():
    text = "Use $9.99 (999 points) of Amazon Rewards Visa Card points Learn More"
    assert purchaser.parse_points_amount(text) == 9.99


def test_parse_points_amount_whole_dollars():
    text = "Use $5 (500 points) of Amazon Rewards Visa Card points"
    assert purchaser.parse_points_amount(text) == 5.0


def test_parse_points_amount_no_match_returns_none():
    assert purchaser.parse_points_amount("Add audiobook for $7.47") is None
    assert purchaser.parse_points_amount("") is None
    assert purchaser.parse_points_amount(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_purchaser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.purchaser'`.

- [ ] **Step 3: Create the module with constants and the parser**

Create `src/purchaser.py`:

```python
"""Auto-purchase a Kindle sample with 1-Click using Amazon Rewards points.

The orchestration in `attempt_purchase` is unit-tested by monkeypatching the
thin DOM helpers below. The actual DOM helpers are validated live.
"""
import logging
import os
import re
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

POINTS_CHECKBOX = '#balance-checkbox-0'
BUY_NOW_BUTTON = '#one-click-button'
POINTS_LABEL_PHRASE = 'Amazon Rewards Visa Card points'

# Signals that an order succeeded / the book is now owned
CONFIRM_SELECTORS = [
    'button:has-text("Read Now")', 'a:has-text("Read Now")',
    '#kindle-reader-button', 'a[href*="/read/"]',
    'input[value*="Read Now"]', '#kop-button-ingress',
]


def parse_points_amount(label_text: Optional[str]) -> Optional[float]:
    """Extract the dollar amount from a points checkbox label.

    Example: "Use $9.99 (999 points) of Amazon Rewards Visa Card points" -> 9.99
    Returns None if no amount is found.
    """
    if not label_text:
        return None
    match = re.search(r'\$(\d+(?:\.\d{2})?)', label_text)
    if not match:
        return None
    return float(match.group(1))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_purchaser.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/purchaser.py tests/test_purchaser.py
git commit -m "feat(purchaser): add points label parsing"
```

---

### Task 3: `purchaser.py` — DOM helpers

**Files:**
- Modify: `src/purchaser.py`

(No unit tests — these thin wrappers are validated live; Task 4 tests the orchestration that uses them via monkeypatching.)

- [ ] **Step 1: Add the DOM helper functions**

Append to `src/purchaser.py`:

```python
def get_points_label_text(page) -> Optional[str]:
    """Read the full points-checkbox label text, e.g.
    'Use $9.99 (999 points) of Amazon Rewards Visa Card points'.
    Returns None if the points checkbox is not present."""
    try:
        cb = page.locator(POINTS_CHECKBOX)
        if cb.count() == 0:
            return None
        container = cb.locator(
            f"xpath=ancestor::*[contains(normalize-space(.), '{POINTS_LABEL_PHRASE}')][1]"
        )
        if container.count() == 0:
            return None
        return container.first.inner_text().strip()
    except Exception as e:
        logger.debug(f"get_points_label_text failed: {e}")
        return None


def check_points_box(page) -> bool:
    """Check ONLY the points checkbox (never the adjacent audiobook checkbox).
    Returns True if it ends up checked."""
    try:
        cb = page.locator(POINTS_CHECKBOX).first
        if cb.count() == 0:
            return False
        if not cb.is_checked():
            cb.check()
        return cb.is_checked()
    except Exception as e:
        logger.debug(f"check_points_box failed: {e}")
        return False


def click_buy_now(page) -> None:
    """Click the 1-Click buy button. Places the order instantly."""
    page.locator(BUY_NOW_BUTTON).first.click()


def purchase_confirmed(page) -> bool:
    """After clicking buy, confirm the order placed by detecting a
    'Read Now' / reader signal or order-confirmation text."""
    try:
        page.wait_for_timeout(3000)
    except Exception:
        pass
    for sel in CONFIRM_SELECTORS:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    try:
        body = page.locator('body').inner_text().lower()
        if 'thank you' in body or 'order has been placed' in body or 'you purchased' in body:
            return True
    except Exception:
        pass
    return False


def _save_screenshot(page, screenshot_dir: Optional[str], name: str) -> None:
    if not screenshot_dir:
        return
    try:
        path = os.path.join(screenshot_dir, f"purchase-{name}.png")
        page.screenshot(path=path)
        logger.debug(f"Saved screenshot {path}")
    except Exception as e:
        logger.debug(f"Screenshot failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add src/purchaser.py
git commit -m "feat(purchaser): add DOM helpers for points checkbox and 1-Click"
```

---

### Task 4: `purchaser.py` — `attempt_purchase` orchestration

**Files:**
- Modify: `src/purchaser.py`
- Test: `tests/test_purchaser.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_purchaser.py`:

```python
class _DummyPage:
    """Stand-in page; attempt_purchase's DOM access is monkeypatched away."""
    pass


def _patch(monkeypatch, label, box_ok, confirmed):
    monkeypatch.setattr(purchaser, 'get_points_label_text', lambda page: label)
    monkeypatch.setattr(purchaser, 'check_points_box', lambda page: box_ok)
    monkeypatch.setattr(purchaser, 'click_buy_now', lambda page: None)
    monkeypatch.setattr(purchaser, 'purchase_confirmed', lambda page: confirmed)
    monkeypatch.setattr(purchaser, '_save_screenshot', lambda *a, **k: None)


def test_attempt_purchase_no_points_checkbox(monkeypatch):
    _patch(monkeypatch, label=None, box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 3.99)
    assert result['success'] is False
    assert 'no points' in result['reason'].lower()


def test_attempt_purchase_partial_coverage_skipped(monkeypatch):
    _patch(monkeypatch, label="Use $3.00 (300 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 5.00,
                                        require_full_coverage=True)
    assert result['success'] is False
    assert 'cover' in result['reason'].lower()


def test_attempt_purchase_success(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99,
                                        require_full_coverage=True)
    assert result['success'] is True
    assert result['points_applied'] == 4.99


def test_attempt_purchase_box_check_fails(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=False, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99)
    assert result['success'] is False
    assert 'box' in result['reason'].lower()


def test_attempt_purchase_not_confirmed(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=False)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99)
    assert result['success'] is False
    assert 'confirm' in result['reason'].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_purchaser.py -v`
Expected: FAIL — `AttributeError: module 'src.purchaser' has no attribute 'attempt_purchase'`.

- [ ] **Step 3: Implement `attempt_purchase`**

Append to `src/purchaser.py`:

```python
def attempt_purchase(page, asin: str, current_price: float,
                     require_full_coverage: bool = True,
                     screenshot_dir: Optional[str] = None,
                     action_delay: float = 0.5) -> Dict[str, Any]:
    """Attempt to buy `asin` with 1-Click, applying Rewards points.

    Returns {"success": bool, "points_applied": float|None, "reason": str}.
    Only returns success after a confirmed order.
    """
    label = get_points_label_text(page)
    if not label:
        return {"success": False, "points_applied": None, "reason": "no points checkbox"}

    amount = parse_points_amount(label)
    if amount is None:
        return {"success": False, "points_applied": None,
                "reason": "could not parse points amount"}

    if require_full_coverage and amount + 1e-9 < current_price:
        return {"success": False, "points_applied": None,
                "reason": f"points ${amount:.2f} do not cover ${current_price:.2f}"}

    _save_screenshot(page, screenshot_dir, f"{asin}-before")

    if not check_points_box(page):
        return {"success": False, "points_applied": None,
                "reason": "could not check points box"}

    logger.info(f"Placing 1-Click order for {asin} (points ${amount:.2f})")
    click_buy_now(page)
    time.sleep(action_delay)

    confirmed = purchase_confirmed(page)
    _save_screenshot(page, screenshot_dir, f"{asin}-after")

    if not confirmed:
        return {"success": False, "points_applied": None,
                "reason": "no purchase confirmation"}

    return {"success": True, "points_applied": amount, "reason": "purchased"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_purchaser.py -v`
Expected: PASS (8 passed total in the file).

- [ ] **Step 5: Commit**

```bash
git add src/purchaser.py tests/test_purchaser.py
git commit -m "feat(purchaser): add attempt_purchase orchestration"
```

---

### Task 5: Email "Auto-purchased" badge

**Files:**
- Modify: `src/email_notifier.py`
- Test: `tests/test_email_notifier.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_email_notifier.py`:

```python
def test_auto_purchased_book_shows_badge_and_read_now():
    books = [{
        'asin': 'B0AUTO0001',
        'title': 'Auto Bought Novel',
        'author': 'A. Writer',
        'cover_url': 'https://example.com/c.jpg',
        'current_price': 3.99,
        'list_price': 12.99,
        'auto_purchased': True,
        'points_applied': 3.99,
    }]
    html = EmailNotifier.generate_email_html(books)
    assert 'Auto-purchased' in html
    assert 'Read now' in html


def test_non_purchased_book_has_no_badge():
    books = [{
        'asin': 'B0NORMAL01',
        'title': 'Normal Deal',
        'author': 'B. Writer',
        'cover_url': '',
        'current_price': 1.99,
        'list_price': 9.99,
    }]
    html = EmailNotifier.generate_email_html(books)
    assert 'Auto-purchased' not in html
    assert 'Buy now on Amazon' in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_email_notifier.py::test_auto_purchased_book_shows_badge_and_read_now -v`
Expected: FAIL — `assert 'Auto-purchased' in html` fails (badge not rendered).

- [ ] **Step 3: Add the badge CSS**

In `src/email_notifier.py`, add a CSS rule right after the `.match-reason::before` block (after line ~316, before `{css_extra}`):

```python
        .auto-purchased {{
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin: 6px 0;
        }}
```

- [ ] **Step 4: Render the badge and swap the button**

In `_generate_book_html`, after the `match_reason` block (after line ~101, before "Format price display"), add:

```python
        # Auto-purchased badge
        auto_purchased = book.get('auto_purchased')
        if auto_purchased:
            book_html += """
                <div class="auto-purchased">Auto-purchased</div>
"""
```

Then change the final button block. Replace:

```python
                <a href="{amazon_link}" class="buy-button">Buy now on Amazon</a>
```

with:

```python
                <a href="{amazon_link}" class="buy-button">{'Read now' if auto_purchased else 'Buy now on Amazon'}</a>
```

(Use single quotes inside the replacement field — the surrounding f-string is triple-double-quoted, and reusing `"` inside breaks on Python < 3.12.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_email_notifier.py -v`
Expected: PASS (all email tests, including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/email_notifier.py tests/test_email_notifier.py
git commit -m "feat(email): add Auto-purchased badge and Read now link"
```

---

### Task 6: Wire auto-purchase into Phase 1 of `check_deals.py`

**Files:**
- Modify: `src/check_deals.py`

(No new unit test — Phase 1 requires a live browser + MySQL. Covered by the purchaser/db/email unit tests above and manual live verification in Task 8.)

- [ ] **Step 1: Import the purchaser**

In `src/check_deals.py`, add to the imports (after line 18, `from email_notifier import EmailNotifier`):

```python
import purchaser
```

- [ ] **Step 2: Read auto-purchase config and init counters**

In `check_deals(...)`, after `amazon_domain = config.get('amazon.domain', 'amazon.com')` (around line 830), add:

```python
    # Auto-purchase settings
    ap_enabled = config.get('auto_purchase.enabled', False)
    ap_max_price = config.get('auto_purchase.max_price', 5.00)
    ap_require_full = config.get('auto_purchase.require_points_full_coverage', True)
    ap_max_per_run = config.get('auto_purchase.max_purchases_per_run', 5)
    action_delay = config.get('scraping.action_delay', 500)
    screenshot_dir = os.path.dirname(session_path)
    run_purchase_count = 0
    purchased_asins = []
```

- [ ] **Step 3: Insert the purchase hook in the Phase 1 loop**

In the Phase 1 per-book loop, locate the block (around lines 941-973):

```python
                        # Check if should notify (from bulk pre-fetch)
                        last_notified_price = bulk_last_notifs.get(asin)
                        notify = should_notify(current_price, list_price, last_notified_price)

                        # Wrap all per-book writes in a single atomic batch
                        if not dry_run:
                            with db.batch_writes():
                                # Update metadata if we got any new data from scraping
                                if scraped_title or scraped_author or scraped_cover:
                                    logger.debug(f"Updating metadata for {asin}")
                                    db.update_book_metadata(asin, title, author, cover_url)
                                db.add_price_history(asin, current_price, list_price)
                                if notify:
                                    db.add_notification(asin, current_price)
                        else:
                            # dry_run: still update metadata in-memory log but no DB writes
                            if scraped_title or scraped_author or scraped_cover:
                                logger.debug(f"Updating metadata for {asin}")

                        if notify:
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
                            tracked_deals.append(deal)
```

Replace that entire block with:

```python
                        # Check if should notify (from bulk pre-fetch)
                        last_notified_price = bulk_last_notifs.get(asin)
                        notify = should_notify(current_price, list_price, last_notified_price)

                        # Auto-purchase: tracked sample, qualifies as a deal, <= cap,
                        # points fully cover, not already bought, under per-run cap.
                        auto_purchased = False
                        points_applied = None
                        deal_qualifies = is_deal(current_price, list_price)
                        if (ap_enabled and not dry_run and deal_qualifies
                                and current_price is not None
                                and current_price <= ap_max_price
                                and run_purchase_count < ap_max_per_run
                                and not db.is_purchased(asin)):
                            result = purchaser.attempt_purchase(
                                page, asin, current_price,
                                require_full_coverage=ap_require_full,
                                screenshot_dir=screenshot_dir,
                                action_delay=action_delay / 1000
                            )
                            if result['success']:
                                auto_purchased = True
                                points_applied = result['points_applied']
                                run_purchase_count += 1
                                # Idempotency: record immediately (before email)
                                db.add_purchase(asin, current_price, points_applied)
                                purchased_asins.append(asin)
                                logger.info(
                                    f"AUTO-PURCHASED {title} - ${current_price:.2f} "
                                    f"(points ${points_applied:.2f})"
                                )
                            else:
                                logger.info(f"Auto-purchase skipped for {title}: {result['reason']}")
                        elif (ap_enabled and dry_run and deal_qualifies
                              and current_price is not None and current_price <= ap_max_price):
                            logger.info(f"DRY RUN: would attempt auto-purchase {title} (${current_price:.2f})")

                        # Record a notification if we're notifying OR we auto-purchased
                        notify_record = notify or auto_purchased

                        # Wrap all per-book writes in a single atomic batch
                        if not dry_run:
                            with db.batch_writes():
                                # Update metadata if we got any new data from scraping
                                if scraped_title or scraped_author or scraped_cover:
                                    logger.debug(f"Updating metadata for {asin}")
                                    db.update_book_metadata(asin, title, author, cover_url)
                                db.add_price_history(asin, current_price, list_price)
                                if notify_record:
                                    db.add_notification(asin, current_price)
                        else:
                            # dry_run: still update metadata in-memory log but no DB writes
                            if scraped_title or scraped_author or scraped_cover:
                                logger.debug(f"Updating metadata for {asin}")

                        if notify_record:
                            savings_percent = calculate_savings_percent(current_price, list_price)

                            deal = {
                                'asin': asin,
                                'title': title,
                                'author': author,
                                'cover_url': cover_url,
                                'current_price': current_price,
                                'list_price': list_price,
                                'previous_price': previous_price,
                                'savings_percent': savings_percent,
                                'auto_purchased': auto_purchased,
                                'points_applied': points_applied
                            }
                            tracked_deals.append(deal)
```

- [ ] **Step 4: Untrack purchased books AFTER the email send**

In `check_deals(...)`, locate the end of the email block — the `else: logger.info("No deals found")` (around line 1032-1033). Immediately after that `else` block and before the "Report samples that have owned copies" section (around line 1035), add:

```python
    # After the email: stop tracking books we just bought (now owned)
    for asin in purchased_asins:
        db.mark_book_deleted(asin)
    if purchased_asins:
        logger.info(f"Marked {len(purchased_asins)} auto-purchased book(s) as owned/untracked")
```

- [ ] **Step 5: Smoke-check imports and syntax**

Run: `python -c "import ast; ast.parse(open('src/check_deals.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add src/check_deals.py
git commit -m "feat(check_deals): auto-purchase eligible samples in Phase 1"
```

---

### Task 7: Config + documentation

**Files:**
- Modify: `config.yaml.example`
- Modify: `config.yaml` (user's live config — enable the feature per the design)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the config section to the example**

In `config.yaml.example`, after the `deals:` block (before `scraping:`), add:

```yaml
auto_purchase:
  enabled: true                       # auto-buy eligible samples with 1-Click
  max_price: 5.00                     # only auto-buy at or below this price
  require_points_full_coverage: true  # only buy when Rewards points cover the whole price
  max_purchases_per_run: 5            # safety cap on purchases per run
```

- [ ] **Step 2: Add the same section to the live config**

In `config.yaml`, add the identical `auto_purchase:` block in the same position (after `deals:`). This enables the feature (the design specifies "on by default").

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`:

1. Under "Database Schema", add a `purchases table` subsection after `deal_checks table`:

````markdown
### purchases table
```sql
CREATE TABLE purchases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asin VARCHAR(20) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    points_applied DECIMAL(10,2),
    purchased_date DATETIME NOT NULL,
    UNIQUE KEY unique_purchase (asin),
    FOREIGN KEY (asin) REFERENCES books(asin)
)
```

Note: Records books auto-purchased via 1-Click with Rewards points. Written immediately on a confirmed purchase (idempotency); the book is marked `is_deleted=1` after the email is sent.
````

2. In the "Core Modules" list, add a `purchaser.py` entry:

```markdown
7. **purchaser.py** - Auto-purchase via 1-Click
   - Buys eligible tracked samples (≤ configurable max_price) when Amazon Rewards points fully cover the price
   - Ticks the points checkbox (#balance-checkbox-0) and clicks Buy now with 1-Click (#one-click-button)
   - Confirms the order before recording it; never touches the adjacent audiobook checkbox
```

3. Under "check_deals.py" Phase 1 description, append: "Phase 1 also auto-purchases eligible samples (see auto_purchase config) using Rewards points, flagging them as 'Auto-purchased' in the email."

4. Under "Configuration Sections", add an `auto_purchase` block describing `enabled`, `max_price`, `require_points_full_coverage`, `max_purchases_per_run`.

- [ ] **Step 4: Commit**

```bash
git add config.yaml.example config.yaml CLAUDE.md
git commit -m "docs: document and enable auto_purchase feature"
```

---

### Task 8: Full test run + live verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all tests pass (DB tests require a running MySQL; if MySQL is unavailable, run `pytest tests/test_purchaser.py tests/test_email_notifier.py tests/test_deal_logic.py -v` and note the DB tests were skipped).

- [ ] **Step 2: Dry-run the real workflow**

Run: `python src/check_deals.py --dry-run --skip-daily --skip-recommendations --verbose`
Expected: Phase 1 runs; for any qualifying sample it logs `DRY RUN: would attempt auto-purchase ...`; no purchases, no DB writes, no email.

- [ ] **Step 3: Report findings to the user**

Summarize: tests passing, dry-run behavior, and the reminder that the FIRST real (non-dry-run) auto-purchase should be watched, since 1-Click is instant and "points applied" can only be confirmed live (before/after screenshots are written to the session directory).
```
