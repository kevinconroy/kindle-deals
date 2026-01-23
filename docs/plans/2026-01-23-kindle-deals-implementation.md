# Kindle Deals Monitor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python system to monitor Kindle samples for price deals and send email notifications.

**Architecture:** SQLite database tracks books and price history. Playwright scrapes Amazon pages. Three main scripts: sample collector, deal checker, and email notifier. Runs locally via cron/scheduled tasks.

**Tech Stack:** Python 3.9+, Playwright, SQLite3, PyYAML, SMTP (built-in)

---

## Task 1: Project Setup and Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `README.md`

**Step 1: Create requirements.txt**

```txt
playwright==1.41.0
pyyaml==6.0.1
pytest==7.4.3
```

**Step 2: Create .gitignore**

```txt
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/

# Testing
.pytest_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Project specific
config.yaml
*.db
*.db-journal
.kindle-deals/
logs/
```

**Step 3: Create README.md**

```markdown
# Kindle Deals Monitor

Monitor Kindle samples for price deals and receive email notifications.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python setup.py
```

## Usage

```bash
# Collect samples
python src/collect_samples.py

# Check for deals
python src/check_deals.py

# Test email notification
python src/send_notification.py --test
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and update with your settings.

Set environment variable: `KINDLE_DEALS_PASSWORD` for email SMTP password.
```

**Step 4: Commit**

```bash
git add requirements.txt .gitignore README.md
git commit -m "chore: initial project setup

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Database Module with TDD

**Files:**
- Create: `tests/test_database.py`
- Create: `src/database.py`

**Step 1: Write failing test for database initialization**

Create `tests/test_database.py`:

```python
import pytest
import tempfile
import os
from src.database import Database


def test_database_init_creates_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)

        # Verify tables exist
        conn = db.get_connection()
        cursor = conn.cursor()

        # Check books table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books'")
        assert cursor.fetchone() is not None

        # Check price_history table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_history'")
        assert cursor.fetchone() is not None

        # Check notifications table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'")
        assert cursor.fetchone() is not None

        db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_database_init_creates_tables -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.database'"

**Step 3: Write minimal implementation**

Create `src/database.py`:

```python
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()

        # Books table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT,
                cover_url TEXT,
                date_added TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Price history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                price REAL,
                list_price REAL,
                check_date TEXT NOT NULL,
                FOREIGN KEY (asin) REFERENCES books(asin)
            )
        """)

        # Notifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                notified_price REAL NOT NULL,
                notified_date TEXT NOT NULL,
                FOREIGN KEY (asin) REFERENCES books(asin)
            )
        """)

        self.conn.commit()

    def get_connection(self):
        return self.conn

    def close(self):
        self.conn.close()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_database.py::test_database_init_creates_tables -v`
Expected: PASS

**Step 5: Write failing test for adding a book**

Add to `tests/test_database.py`:

```python
def test_add_book():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)

        book_data = {
            "asin": "B001234567",
            "title": "Test Book",
            "author": "Test Author",
            "cover_url": "https://example.com/cover.jpg"
        }

        db.add_book(**book_data)

        # Verify book was added
        book = db.get_book("B001234567")
        assert book is not None
        assert book["title"] == "Test Book"
        assert book["author"] == "Test Author"
        assert book["is_active"] == 1

        db.close()
```

**Step 6: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_add_book -v`
Expected: FAIL with "AttributeError: 'Database' object has no attribute 'add_book'"

**Step 7: Implement add_book and get_book methods**

Add to `src/database.py`:

```python
    def add_book(self, asin: str, title: str, author: Optional[str] = None,
                 cover_url: Optional[str] = None):
        cursor = self.conn.cursor()
        date_added = datetime.now().isoformat()

        cursor.execute("""
            INSERT OR IGNORE INTO books (asin, title, author, cover_url, date_added)
            VALUES (?, ?, ?, ?, ?)
        """, (asin, title, author, cover_url, date_added))

        self.conn.commit()

    def get_book(self, asin: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM books WHERE asin = ?", (asin,))
        row = cursor.fetchone()
        return dict(row) if row else None
```

**Step 8: Run test to verify it passes**

Run: `pytest tests/test_database.py::test_add_book -v`
Expected: PASS

**Step 9: Write failing test for price history**

Add to `tests/test_database.py`:

```python
def test_add_price_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)

        # Add a book first
        db.add_book("B001234567", "Test Book")

        # Add price history
        db.add_price_history("B001234567", price=2.99, list_price=9.99)

        # Get latest price
        latest = db.get_latest_price("B001234567")
        assert latest is not None
        assert latest["price"] == 2.99
        assert latest["list_price"] == 9.99

        db.close()
```

**Step 10: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_add_price_history -v`
Expected: FAIL with "AttributeError: 'Database' object has no attribute 'add_price_history'"

**Step 11: Implement price history methods**

Add to `src/database.py`:

```python
    def add_price_history(self, asin: str, price: Optional[float],
                         list_price: Optional[float]):
        cursor = self.conn.cursor()
        check_date = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO price_history (asin, price, list_price, check_date)
            VALUES (?, ?, ?, ?)
        """, (asin, price, list_price, check_date))

        self.conn.commit()

    def get_latest_price(self, asin: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM price_history
            WHERE asin = ?
            ORDER BY check_date DESC
            LIMIT 1
        """, (asin,))
        row = cursor.fetchone()
        return dict(row) if row else None
```

**Step 12: Run test to verify it passes**

Run: `pytest tests/test_database.py::test_add_price_history -v`
Expected: PASS

**Step 13: Write failing test for notification tracking**

Add to `tests/test_database.py`:

```python
def test_notification_tracking():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)

        db.add_book("B001234567", "Test Book")

        # Add notification
        db.add_notification("B001234567", notified_price=2.99)

        # Get last notification
        last_notif = db.get_last_notification("B001234567")
        assert last_notif is not None
        assert last_notif["notified_price"] == 2.99

        db.close()
```

**Step 14: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_notification_tracking -v`
Expected: FAIL with "AttributeError: 'Database' object has no attribute 'add_notification'"

**Step 15: Implement notification methods**

Add to `src/database.py`:

```python
    def add_notification(self, asin: str, notified_price: float):
        cursor = self.conn.cursor()
        notified_date = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO notifications (asin, notified_price, notified_date)
            VALUES (?, ?, ?)
        """, (asin, notified_price, notified_date))

        self.conn.commit()

    def get_last_notification(self, asin: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM notifications
            WHERE asin = ?
            ORDER BY notified_date DESC
            LIMIT 1
        """, (asin,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_active_books(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM books WHERE is_active = 1")
        return [dict(row) for row in cursor.fetchall()]
```

**Step 16: Run test to verify it passes**

Run: `pytest tests/test_database.py::test_notification_tracking -v`
Expected: PASS

**Step 17: Run all database tests**

Run: `pytest tests/test_database.py -v`
Expected: All tests PASS

**Step 18: Commit**

```bash
git add tests/test_database.py src/database.py
git commit -m "feat: add database module with tests

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Deal Logic Module with TDD

**Files:**
- Create: `tests/test_deal_logic.py`
- Create: `src/deal_logic.py`

**Step 1: Write failing test for deal criteria**

Create `tests/test_deal_logic.py`:

```python
import pytest
from src.deal_logic import is_deal, should_notify


def test_is_deal_under_four_dollars():
    assert is_deal(current_price=3.99, list_price=9.99) is True
    assert is_deal(current_price=3.50, list_price=15.00) is True


def test_is_deal_fifty_percent_off():
    assert is_deal(current_price=5.00, list_price=10.00) is True
    assert is_deal(current_price=4.99, list_price=10.00) is True


def test_not_a_deal():
    assert is_deal(current_price=5.00, list_price=9.00) is False
    assert is_deal(current_price=6.00, list_price=10.00) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_deal_logic.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.deal_logic'"

**Step 3: Write minimal implementation**

Create `src/deal_logic.py`:

```python
from typing import Optional


def is_deal(current_price: float, list_price: float) -> bool:
    """
    Determine if a book meets deal criteria.

    Deal criteria:
    - Price under $4.00, OR
    - At least 50% off list price
    """
    if current_price < 4.00:
        return True

    if current_price <= list_price * 0.5:
        return True

    return False


def should_notify(current_price: float, list_price: float,
                 last_notified_price: Optional[float]) -> bool:
    """
    Determine if user should be notified about this deal.

    Notification rules:
    - Notify once when book first meets deal criteria
    - Notify again only if price drops further
    """
    if not is_deal(current_price, list_price):
        return False

    if last_notified_price is None:
        return True  # First time deal

    if current_price < last_notified_price:
        return True  # Price dropped further

    return False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_deal_logic.py -v`
Expected: PASS

**Step 5: Write failing test for notification logic**

Add to `tests/test_deal_logic.py`:

```python
def test_should_notify_first_time_deal():
    # First time deal - should notify
    assert should_notify(
        current_price=3.99,
        list_price=9.99,
        last_notified_price=None
    ) is True


def test_should_notify_price_drop():
    # Price dropped from $3.99 to $2.99 - should notify
    assert should_notify(
        current_price=2.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is True


def test_should_not_notify_same_price():
    # Same price as last notification - should not notify
    assert should_notify(
        current_price=3.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is False


def test_should_not_notify_price_increase():
    # Price increased - should not notify
    assert should_notify(
        current_price=4.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is False


def test_should_not_notify_not_a_deal():
    # Not a deal - should not notify
    assert should_notify(
        current_price=7.00,
        list_price=9.99,
        last_notified_price=None
    ) is False
```

**Step 6: Run test to verify it passes**

Run: `pytest tests/test_deal_logic.py -v`
Expected: All tests PASS (implementation already covers these cases)

**Step 7: Commit**

```bash
git add tests/test_deal_logic.py src/deal_logic.py
git commit -m "feat: add deal logic with tests

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Configuration Module

**Files:**
- Create: `config.yaml.example`
- Create: `src/config.py`
- Create: `tests/test_config.py`

**Step 1: Create example config**

Create `config.yaml.example`:

```yaml
amazon:
  domain: amazon.com
  sample_check_frequency: weekly
  deal_check_frequency: daily

notifications:
  email:
    smtp_server: smtp.gmail.com
    smtp_port: 587
    from_address: your-email@gmail.com
    to_address: your-email@gmail.com
    password_source: env

deal_criteria:
  max_price: 4.00
  min_discount_percent: 50

storage:
  database_path: ~/.kindle-deals/deals.db
  browser_session_path: ~/.kindle-deals/browser-session
  backup_enabled: true
  backup_retention_days: 30

scraping:
  headless: true
  page_timeout: 30
  retry_attempts: 3
  delay_between_requests: 2
```

**Step 2: Write failing test for config loading**

Create `tests/test_config.py`:

```python
import pytest
import tempfile
import os
from src.config import Config


def test_load_config():
    config_content = """
amazon:
  domain: amazon.com

notifications:
  email:
    smtp_server: smtp.gmail.com
    smtp_port: 587

deal_criteria:
  max_price: 4.00
  min_discount_percent: 50
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(config_content)

        config = Config(config_path)
        assert config.get("amazon.domain") == "amazon.com"
        assert config.get("deal_criteria.max_price") == 4.00
        assert config.get("notifications.email.smtp_port") == 587
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_load_config -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.config'"

**Step 4: Write minimal implementation**

Create `src/config.py`:

```python
import yaml
import os
from typing import Any


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.data = self._load_config()

    def _load_config(self) -> dict:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value using dot notation (e.g., 'amazon.domain')"""
        keys = key.split('.')
        value = self.data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_email_password(self) -> str:
        """Get email password from environment variable"""
        password = os.environ.get('KINDLE_DEALS_PASSWORD')
        if not password:
            raise ValueError("KINDLE_DEALS_PASSWORD environment variable not set")
        return password
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_load_config -v`
Expected: PASS

**Step 6: Commit**

```bash
git add config.yaml.example src/config.py tests/test_config.py
git commit -m "feat: add configuration module

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Email Notifier Module

**Files:**
- Create: `src/email_notifier.py`
- Create: `tests/test_email_notifier.py`

**Step 1: Write failing test for email HTML generation**

Create `tests/test_email_notifier.py`:

```python
import pytest
from src.email_notifier import EmailNotifier


def test_generate_email_html():
    book_data = {
        "asin": "B001234567",
        "title": "Test Book Title",
        "author": "Test Author",
        "cover_url": "https://example.com/cover.jpg",
        "current_price": 2.99,
        "list_price": 9.99,
        "savings_percent": 70
    }

    html = EmailNotifier.generate_email_html([book_data])

    assert "Test Book Title" in html
    assert "Test Author" in html
    assert "$2.99" in html
    assert "$9.99" in html
    assert "70%" in html
    assert book_data["cover_url"] in html
    assert f"amazon.com/dp/{book_data['asin']}" in html
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_email_notifier.py::test_generate_email_html -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.email_notifier'"

**Step 3: Write minimal implementation**

Create `src/email_notifier.py`:

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, smtp_server: str, smtp_port: int,
                 from_address: str, password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.from_address = from_address
        self.password = password

    @staticmethod
    def generate_email_html(books: List[Dict[str, Any]]) -> str:
        """Generate HTML email content for book deals"""
        html_parts = ["""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; }
        .book {
            border: 1px solid #ddd;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
        }
        .book img { max-width: 150px; float: left; margin-right: 15px; }
        .book h2 { margin-top: 0; }
        .price { color: #B12704; font-weight: bold; font-size: 1.2em; }
        .list-price { text-decoration: line-through; color: #666; }
        .savings { color: #007600; font-weight: bold; }
        .clear { clear: both; }
    </style>
</head>
<body>
    <h1>Kindle Deals Alert!</h1>
"""]

        for book in books:
            savings_percent = book.get('savings_percent', 0)
            amazon_link = f"https://amazon.com/dp/{book['asin']}"

            book_html = f"""
    <div class="book">
        <img src="{book.get('cover_url', '')}" alt="{book['title']}" />
        <h2>{book['title']}</h2>
        <p><strong>Author:</strong> {book.get('author', 'Unknown')}</p>
        <p>
            <span class="price">${book['current_price']:.2f}</span>
            <span class="list-price">${book['list_price']:.2f}</span>
            <span class="savings">Save {savings_percent:.0f}%</span>
        </p>
        <p><a href="{amazon_link}">Buy now on Amazon</a></p>
        <div class="clear"></div>
    </div>
"""
            html_parts.append(book_html)

        html_parts.append("""
</body>
</html>
""")

        return "".join(html_parts)

    def send_email(self, to_address: str, subject: str, html_content: str):
        """Send HTML email"""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_address
        msg['To'] = to_address

        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.from_address, self.password)
                server.send_message(msg)
            logger.info(f"Email sent successfully to {to_address}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_email_notifier.py::test_generate_email_html -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/email_notifier.py tests/test_email_notifier.py
git commit -m "feat: add email notifier module

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Scraper Utilities Module

**Files:**
- Create: `src/scraper.py`

**Step 1: Create scraper utilities (no test - requires live browser)**

Create `src/scraper.py`:

```python
from playwright.sync_api import sync_playwright, Page, Browser
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AmazonScraper:
    def __init__(self, session_path: str, headless: bool = True,
                 page_timeout: int = 30000):
        self.session_path = session_path
        self.headless = headless
        self.page_timeout = page_timeout
        self.playwright = None
        self.browser = None
        self.context = None

    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)

        # Use persistent context to save login session
        self.context = self.browser.new_context(
            storage_state=self.session_path if self._session_exists() else None
        )
        self.context.set_default_timeout(self.page_timeout)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            # Save session state
            self.context.storage_state(path=self.session_path)
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _session_exists(self) -> bool:
        import os
        return os.path.exists(self.session_path)

    def new_page(self) -> Page:
        return self.context.new_page()

    def retry_with_backoff(self, func, max_attempts: int = 3,
                          initial_delay: float = 1.0):
        """Retry function with exponential backoff"""
        delay = initial_delay
        last_exception = None

        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2

        raise last_exception


def extract_price(price_text: Optional[str]) -> Optional[float]:
    """Extract price from text like '$3.99' or '3.99'"""
    if not price_text:
        return None

    # Remove currency symbols and whitespace
    cleaned = price_text.replace('$', '').replace(',', '').strip()

    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Could not parse price: {price_text}")
        return None


def calculate_savings_percent(current_price: float, list_price: float) -> int:
    """Calculate savings percentage"""
    if list_price == 0:
        return 0

    savings = ((list_price - current_price) / list_price) * 100
    return int(round(savings))
```

**Step 2: Commit**

```bash
git add src/scraper.py
git commit -m "feat: add scraper utilities

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Sample Collector Script

**Files:**
- Create: `src/collect_samples.py`

**Step 1: Create sample collector script**

Create `src/collect_samples.py`:

```python
#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

from config import Config
from database import Database
from scraper import AmazonScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def collect_samples(config: Config, db: Database, dry_run: bool = False):
    """Collect Kindle samples from Amazon My Books page"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        try:
            # Navigate to Amazon My Books
            logger.info("Navigating to Amazon My Books...")
            page.goto("https://www.amazon.com/hz/mycd/myx")

            # Wait for page to load
            page.wait_for_load_state('networkidle')

            # Check if logged in (look for sign-in elements)
            if page.locator('input[name="email"]').count() > 0:
                logger.error("Not logged in. Please run with --headless false and log in manually.")
                sys.exit(2)

            # Filter for samples
            logger.info("Filtering for Kindle samples...")
            # Note: Actual selectors would need to be determined by inspecting the page
            # This is a placeholder implementation

            samples = []
            sample_elements = page.locator('[data-content-type="Sample"]').all()

            logger.info(f"Found {len(sample_elements)} samples")

            for element in sample_elements:
                try:
                    title = element.locator('.title').inner_text()
                    author = element.locator('.author').inner_text()

                    # Extract ASIN from element attributes or links
                    asin = element.get_attribute('data-asin')

                    # Extract cover URL
                    cover_img = element.locator('img').first
                    cover_url = cover_img.get_attribute('src') if cover_img else None

                    sample = {
                        'asin': asin,
                        'title': title,
                        'author': author,
                        'cover_url': cover_url
                    }
                    samples.append(sample)
                    logger.info(f"Found: {title} by {author}")

                except Exception as e:
                    logger.warning(f"Failed to extract sample data: {e}")
                    continue

            if dry_run:
                logger.info(f"DRY RUN: Would add {len(samples)} samples to database")
                return

            # Add samples to database
            for sample in samples:
                db.add_book(**sample)
                logger.info(f"Added to database: {sample['title']}")

            logger.info(f"Successfully collected {len(samples)} samples")

        except Exception as e:
            logger.error(f"Failed to collect samples: {e}")
            raise
        finally:
            page.close()


def main():
    parser = argparse.ArgumentParser(description='Collect Kindle samples from Amazon')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config = Config(args.config)
        db_path = os.path.expanduser(config.get('storage.database_path'))
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        db = Database(db_path)
        collect_samples(config, db, dry_run=args.dry_run)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

**Step 2: Make script executable**

Run: `chmod +x src/collect_samples.py`

**Step 3: Commit**

```bash
git add src/collect_samples.py
git commit -m "feat: add sample collector script

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Deal Checker Script

**Files:**
- Create: `src/check_deals.py`

**Step 1: Create deal checker script**

Create `src/check_deals.py`:

```python
#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import time
from typing import List, Dict, Any

from config import Config
from database import Database
from scraper import AmazonScraper, extract_price, calculate_savings_percent
from deal_logic import should_notify
from email_notifier import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def scrape_book_price(page, asin: str, delay: float = 2.0) -> Dict[str, Any]:
    """Scrape price information for a book"""
    url = f"https://www.amazon.com/dp/{asin}"

    try:
        logger.debug(f"Scraping {url}")
        page.goto(url)
        page.wait_for_load_state('networkidle')

        # Extract Kindle price
        kindle_price_elem = page.locator('#kindle-price, .kindle-price').first
        kindle_price_text = kindle_price_elem.inner_text() if kindle_price_elem else None
        kindle_price = extract_price(kindle_price_text)

        # Extract list price
        list_price_elem = page.locator('.list-price, [data-a-strike="true"]').first
        list_price_text = list_price_elem.inner_text() if list_price_elem else None
        list_price = extract_price(list_price_text) or kindle_price

        time.sleep(delay)  # Rate limiting

        return {
            'kindle_price': kindle_price,
            'list_price': list_price
        }

    except Exception as e:
        logger.error(f"Failed to scrape price for {asin}: {e}")
        return {
            'kindle_price': None,
            'list_price': None
        }


def check_deals(config: Config, db: Database, target_asin: str = None):
    """Check for deals on tracked books"""
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))
    headless = config.get('scraping.headless', True)
    page_timeout = config.get('scraping.page_timeout', 30) * 1000
    delay = config.get('scraping.delay_between_requests', 2)

    # Get books to check
    if target_asin:
        book = db.get_book(target_asin)
        books = [book] if book else []
    else:
        books = db.get_active_books()

    logger.info(f"Checking {len(books)} books for deals...")

    deals_found = []

    with AmazonScraper(session_path, headless, page_timeout) as scraper:
        page = scraper.new_page()

        for book in books:
            asin = book['asin']
            logger.info(f"Checking {book['title']}...")

            # Scrape current price
            price_data = scraper.retry_with_backoff(
                lambda: scrape_book_price(page, asin, delay)
            )

            current_price = price_data['kindle_price']
            list_price = price_data['list_price']

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

        page.close()

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
        db_path = os.path.expanduser(config.get('storage.database_path'))

        db = Database(db_path)
        check_deals(config, db, target_asin=args.asin)
        db.close()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

**Step 2: Make script executable**

Run: `chmod +x src/check_deals.py`

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "feat: add deal checker script

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Email Test Script

**Files:**
- Create: `src/send_notification.py`

**Step 1: Create email test script**

Create `src/send_notification.py`:

```python
#!/usr/bin/env python3
import argparse
import logging
import sys

from config import Config
from email_notifier import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def send_test_email(config: Config):
    """Send a test email notification"""

    # Create test book data
    test_books = [
        {
            'asin': 'B00TEST001',
            'title': 'Test Book: The Art of Testing',
            'author': 'Test Author',
            'cover_url': 'https://m.media-amazon.com/images/I/placeholder.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
            'savings_percent': 70
        }
    ]

    logger.info("Creating email notifier...")
    notifier = EmailNotifier(
        smtp_server=config.get('notifications.email.smtp_server'),
        smtp_port=config.get('notifications.email.smtp_port'),
        from_address=config.get('notifications.email.from_address'),
        password=config.get_email_password()
    )

    logger.info("Generating email HTML...")
    html = EmailNotifier.generate_email_html(test_books)

    subject = "Kindle Deals Test Email"
    to_address = config.get('notifications.email.to_address')

    logger.info(f"Sending test email to {to_address}...")
    notifier.send_email(to_address, subject, html)

    logger.info("Test email sent successfully!")


def main():
    parser = argparse.ArgumentParser(description='Send test email notification')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--test', action='store_true', help='Send test email')

    args = parser.parse_args()

    if not args.test:
        parser.print_help()
        sys.exit(1)

    try:
        config = Config(args.config)
        send_test_email(config)
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

**Step 2: Make script executable**

Run: `chmod +x src/send_notification.py`

**Step 3: Commit**

```bash
git add src/send_notification.py
git commit -m "feat: add email test script

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Setup Script

**Files:**
- Create: `setup.py`

**Step 1: Create setup script**

Create `setup.py`:

```python
#!/usr/bin/env python3
import os
import sys
import shutil
from pathlib import Path

from src.config import Config
from src.database import Database


def main():
    print("=" * 60)
    print("Kindle Deals Monitor - Setup")
    print("=" * 60)
    print()

    # Check for config file
    if not os.path.exists('config.yaml'):
        print("Creating config.yaml from template...")
        if os.path.exists('config.yaml.example'):
            shutil.copy('config.yaml.example', 'config.yaml')
            print("✓ Created config.yaml")
            print()
            print("Please edit config.yaml and update:")
            print("  - Email addresses")
            print("  - SMTP server settings (if not using Gmail)")
            print()
            print("Set environment variable:")
            print("  export KINDLE_DEALS_PASSWORD='your-email-password'")
            print()
            response = input("Press Enter when ready to continue...")
        else:
            print("ERROR: config.yaml.example not found")
            sys.exit(1)

    # Load config
    try:
        config = Config('config.yaml')
        print("✓ Configuration loaded")
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        sys.exit(1)

    # Create directories
    db_path = os.path.expanduser(config.get('storage.database_path'))
    session_path = os.path.expanduser(config.get('storage.browser_session_path'))

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(os.path.dirname(session_path), exist_ok=True)
    print("✓ Created storage directories")

    # Initialize database
    db = Database(db_path)
    db.close()
    print("✓ Database initialized")

    # Test email configuration
    print()
    print("Testing email configuration...")
    try:
        password = config.get_email_password()
        print("✓ Email password found in environment")

        response = input("Send test email? (y/n): ")
        if response.lower() == 'y':
            from src.email_notifier import EmailNotifier

            notifier = EmailNotifier(
                smtp_server=config.get('notifications.email.smtp_server'),
                smtp_port=config.get('notifications.email.smtp_port'),
                from_address=config.get('notifications.email.from_address'),
                password=password
            )

            test_html = "<h1>Kindle Deals Setup Test</h1><p>Email configuration is working!</p>"
            notifier.send_email(
                config.get('notifications.email.to_address'),
                "Kindle Deals Setup Test",
                test_html
            )
            print("✓ Test email sent")

    except Exception as e:
        print(f"⚠ Email test failed: {e}")
        print("You can test email later with: python src/send_notification.py --test")

    # Initial browser login
    print()
    print("Initial browser setup...")
    print("A browser window will open. Please log into Amazon and close the browser.")
    response = input("Press Enter to continue...")

    try:
        from src.scraper import AmazonScraper

        with AmazonScraper(session_path, headless=False) as scraper:
            page = scraper.new_page()
            page.goto("https://www.amazon.com/hz/mycd/myx")
            print("Please log in to Amazon in the browser window...")
            print("When done, close the browser window.")
            page.wait_for_timeout(300000)  # Wait up to 5 minutes

        print("✓ Browser session saved")

    except Exception as e:
        print(f"⚠ Browser setup failed: {e}")
        print("You can set up the browser session later when running collect_samples.py")

    # Print cron setup instructions
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print()
    print("Add these cron entries to schedule automatic runs:")
    print()
    print("# Weekly sample collection (Sundays at 6 AM)")
    print(f"0 6 * * 0 cd {os.getcwd()} && {sys.executable} src/collect_samples.py")
    print()
    print("# Daily deal check (7 AM)")
    print(f"0 7 * * * cd {os.getcwd()} && {sys.executable} src/check_deals.py")
    print()
    print("To add cron entries:")
    print("  crontab -e")
    print()
    print("Manual commands:")
    print(f"  {sys.executable} src/collect_samples.py")
    print(f"  {sys.executable} src/check_deals.py")
    print()


if __name__ == '__main__':
    main()
```

**Step 2: Make script executable**

Run: `chmod +x setup.py`

**Step 3: Commit**

```bash
git add setup.py
git commit -m "feat: add setup script

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 11: Run All Tests

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Fix any import issues**

Add `__init__.py` files if needed:

```bash
touch src/__init__.py
touch tests/__init__.py
```

**Step 3: Update imports in test files if needed**

Ensure all imports use proper module paths.

**Step 4: Commit if changes made**

```bash
git add src/__init__.py tests/__init__.py
git commit -m "chore: add __init__.py files for proper imports

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 12: Create CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

**Step 1: Create CLAUDE.md**

Create `CLAUDE.md`:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run setup
python setup.py

# Run tests
pytest tests/ -v
pytest tests/test_database.py -v
pytest tests/test_deal_logic.py -v
```

### Running Scripts

```bash
# Collect Kindle samples
python src/collect_samples.py
python src/collect_samples.py --dry-run  # Test mode
python src/collect_samples.py --verbose  # Debug mode

# Check for deals
python src/check_deals.py
python src/check_deals.py --asin B01234ABCD  # Check specific book
python src/check_deals.py --verbose  # Debug mode

# Test email notification
python src/send_notification.py --test
```

## Architecture

### Core Components

1. **Database Module** (`src/database.py`): SQLite wrapper for managing books, price history, and notifications
2. **Deal Logic** (`src/deal_logic.py`): Business logic for determining deals and when to notify
3. **Scraper** (`src/scraper.py`): Playwright-based Amazon scraping utilities with session management
4. **Email Notifier** (`src/email_notifier.py`): HTML email generation and SMTP sending
5. **Config** (`src/config.py`): YAML configuration loader with dot notation access

### Scripts

- `collect_samples.py`: Scrapes Amazon "My Books" for Kindle samples, stores in database
- `check_deals.py`: Checks prices for all active books, sends email for qualifying deals
- `send_notification.py`: Test utility for email functionality
- `setup.py`: Interactive setup wizard

### Database Schema

**books**: Tracks Kindle samples
- asin (PK), title, author, cover_url, date_added, is_active

**price_history**: Historical price data
- id (PK), asin (FK), price, list_price, check_date

**notifications**: Tracks when user was notified
- id (PK), asin (FK), notified_price, notified_date

### Deal Logic

A book is a "deal" if:
- Current price < $4.00, OR
- Current price <= 50% of list price

User is notified when:
- First time book meets deal criteria, OR
- Price drops below previously notified price

### Configuration

Config in `config.yaml` with sections:
- `amazon`: Domain, check frequencies
- `notifications.email`: SMTP settings
- `deal_criteria`: Price thresholds
- `storage`: Database and session paths
- `scraping`: Playwright options, rate limiting

Email password from environment: `KINDLE_DEALS_PASSWORD`

### Testing

Tests use pytest with temporary directories for isolation.
- `test_database.py`: Database CRUD operations
- `test_deal_logic.py`: Deal criteria and notification logic
- `test_config.py`: Configuration loading
- `test_email_notifier.py`: HTML email generation

No tests for scraper (requires live browser) - test manually with `--dry-run` and `--verbose` flags.
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Completion Checklist

- [ ] All unit tests passing
- [ ] All scripts executable
- [ ] Config example file created
- [ ] Setup script working
- [ ] Documentation complete (README.md, CLAUDE.md)
- [ ] All code committed to git

## Next Steps After Implementation

1. Test end-to-end workflow manually
2. Run `python setup.py` for initial setup
3. Add cron entries for scheduled execution
4. Monitor logs for issues
5. Consider future enhancements (CloudFormation, web dashboard, etc.)
