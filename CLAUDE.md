# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kindle Deals Monitor is a Python application that tracks price changes on Kindle books in your "My Books" library and sends email notifications when deals are found. The application uses web scraping (via Playwright) to collect your book list from Amazon's "My Books" page and check prices.

## Quick Start Commands

### Development Setup
```bash
# One-line setup
./setup.sh

# Or manually:
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python setup.py

# Edit config.yaml with your settings
```

### Running Tests
```bash
# Run all tests
pytest

# Run specific test module
pytest tests/test_database.py
pytest tests/test_deal_logic.py
pytest tests/test_config.py
pytest tests/test_email_notifier.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src
```

### Running Scripts

**Quick Start (Recommended):**
```bash
# Run complete workflow: sync library + check deals
./check_all_deals.sh

# Dry run (no emails, no database changes)
./check_all_deals.sh --dry-run

# Verbose output
./check_all_deals.sh --verbose

# Skip library sync, only check deals
./check_all_deals.sh --skip-sync

# Skip sample book price checks, only check daily deals
./check_all_deals.sh --skip-samples

# Skip daily deals, only check sample books
./check_all_deals.sh --skip-daily

# Force full sync (disable early stopping)
./check_all_deals.sh --force

# Skip auto-adding samples to collection
./check_all_deals.sh --skip-collections

# Skip recommended book price checks
./check_all_deals.sh --skip-recommendations
```

**Individual Scripts:**
```bash
# Sync Kindle library from Amazon digital console
python src/sync_library.py

# Force full sync (disable early stopping, enable removal tracking)
python src/sync_library.py --force

# Skip auto-adding uncollected samples to collection
python src/sync_library.py --skip-collections

# Check for deals (sample books + daily deals)
python src/check_deals.py

# Check specific book by ASIN
python src/check_deals.py --asin B01234567X

# Skip sample book checks, only check daily deals
python src/check_deals.py --skip-samples

# Skip daily deals, only check sample books
python src/check_deals.py --skip-daily

# Skip recommended book price checks
python src/check_deals.py --skip-recommendations

# Send test email notification
python src/send_notification.py --test

# List samples that have an owned copy (eligible for deletion)
python src/cleanup_samples.py

# List and automatically open cleanup URLs in browser tabs
python src/cleanup_samples.py --open
```

### Cron Schedule

```bash
# Run complete workflow (sync + check deals) at 5 AM daily
0 5 * * * cd /path/to/kindle-deals && ./check_all_deals.sh
```

## Architecture

### Core Modules

The application consists of these main modules:

1. **database.py** - MySQL database interface
   - Uses mysql-connector-python for MySQL connections
   - Manages six tables: books, price_history, notifications, recommendations, deal_checks, purchases
   - Auto-creates database and tables on initialization
   - Provides methods for adding/retrieving books, prices, notifications, and recommendations

2. **deal_logic.py** - Deal detection logic
   - Pure functions with no dependencies
   - Implements deal criteria ($4 and 50% rules)
   - Determines when notifications should be sent

3. **config.py** - Configuration management
   - Loads settings from config.yaml
   - Provides dot-notation access (e.g., config.get("amazon.domain"))
   - All configuration including passwords stored in config.yaml
   - Validates required settings

4. **email_notifier.py** - Email notification system
   - Sends HTML emails via SMTP
   - Generates formatted deal notifications with book covers
   - Two-section layout: "Tracked Deals" and "Recommended Deals" (with backward-compatible flat layout)
   - Shows current price, list price, and previous price for comparison
   - Displays both overall savings and new price drops
   - Supports Gmail SMTP (configurable)

5. **scraper.py** - Web scraping utilities for "My Books"
   - Uses Playwright for browser automation
   - Provides session persistence for authenticated scraping
   - Contains helper functions for price extraction
   - NOTE: Only used for collecting book list, not for price checking

6. **similarity_matcher.py** - Book similarity matching
   - Matches books by author, series, or recommendations
   - Caches data in memory for fast lookups
   - Used by daily deals checker

7. **purchaser.py** - Auto-purchase via 1-Click
   - Buys eligible tracked samples (≤ configurable `max_price`) when Amazon Rewards points fully cover the price
   - Ticks the points checkbox (`#balance-checkbox-0`) and clicks "Buy now with 1-Click" (`#one-click-button`)
   - Confirms the order before recording it; never touches the adjacent audiobook checkbox
   - 1-Click is instant (no review page); writes before/after screenshots to the session dir

### Scripts

**Main Workflow:**
- **check_all_deals.sh** - All-in-one script that runs sync + deal checks
  - Handles virtual environment activation
  - Runs library sync with recommendations
  - Checks deals on sample books and daily deals
  - Supports `--dry-run`, `--verbose`, `--force`, `--skip-sync`, `--skip-samples`, `--skip-daily`, `--skip-collections`, `--skip-recommendations` flags

**Individual Scripts:**
1. **sync_library.py** - Syncs your Kindle library from Amazon digital console using Playwright
   - Scrapes both owned books and samples from `booksAll` URL
   - Classifies items as sample (`is_sample=1`) or owned (`is_sample=0`)
   - Early-stop optimization: stops after N consecutive known ASINs (configurable, default 10)
   - Auto-adds uncollected samples to a configurable collection (e.g., "Read Me 2026")
   - Also scrapes "also bought" recommendations for each sample
   - `--force` disables early stopping and enables removal tracking
   - `--skip-collections` skips collection management
2. **check_deals.py** - Checks book prices, daily deals, and recommended books via web scraping, sends notifications
   - Phase 1: Sample book price checks (also auto-purchases eligible samples — see `auto_purchase` config — paying with Rewards points and flagging them as "Auto-purchased" in the email)
   - Phase 2: Daily deals matching (by author, series, or recommendation)
   - Phase 3: Parallel recommendation price checking using ThreadPoolExecutor with configurable concurrency
   - Supports `--skip-samples`, `--skip-daily`, and `--skip-recommendations` flags for granular control
3. **send_notification.py** - Sends test email notifications

## Database Schema

The application uses MySQL with six tables:

### books table
```sql
CREATE TABLE books (
    asin VARCHAR(20) PRIMARY KEY,
    title VARCHAR(500),
    author VARCHAR(255),
    cover_url VARCHAR(1000),
    date_added DATETIME NOT NULL,
    is_sample TINYINT(1) DEFAULT 1,
    is_deleted TINYINT(1) DEFAULT 0,
    is_recommendation TINYINT(1) DEFAULT 0
)
```

Note: Title can be NULL when books are first synced from library (ASIN only). The check_deals script will fetch and populate title/author/cover_url via web scraping. `is_sample=1` for samples, `0` for owned books. `is_deleted=1` for books removed from library (only tracked during `--force` full syncs). `is_recommendation=1` for books added via recommendation price checking (not in user's library).

### price_history table
```sql
CREATE TABLE price_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asin VARCHAR(20) NOT NULL,
    price DECIMAL(10,2),
    list_price DECIMAL(10,2),
    check_date DATETIME NOT NULL,
    FOREIGN KEY (asin) REFERENCES books(asin)
)
```

### notifications table
```sql
CREATE TABLE notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asin VARCHAR(20) NOT NULL,
    notified_price DECIMAL(10,2) NOT NULL,
    notified_date DATETIME NOT NULL,
    FOREIGN KEY (asin) REFERENCES books(asin)
)
```

### recommendations table
```sql
CREATE TABLE recommendations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_asin VARCHAR(20) NOT NULL,
    recommended_asin VARCHAR(20) NOT NULL,
    created_date DATETIME NOT NULL,
    FOREIGN KEY (source_asin) REFERENCES books(asin),
    INDEX idx_recommended_asin (recommended_asin),
    UNIQUE KEY unique_recommendation (source_asin, recommended_asin)
)
```

Note: Stores Amazon "also bought" recommendations. Only source_asin has a foreign key (user's books); recommended_asin references external books that may not be in the user's library.

### deal_checks table
```sql
CREATE TABLE deal_checks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asin VARCHAR(20) NOT NULL,
    check_date DATE NOT NULL,
    was_deal TINYINT(1) NOT NULL,
    notified TINYINT(1) NOT NULL,
    UNIQUE KEY unique_daily_check (asin, check_date)
)
```

Note: Tracks which daily deals have been checked to prevent duplicate processing on the same day.

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

Note: Records books auto-purchased via 1-Click with Rewards points. Written immediately on a confirmed purchase (idempotency via UNIQUE asin; `is_purchased()` guards against re-buying); the book is marked `is_deleted=1` after the email is sent.

## Deal Logic

### Deal Criteria

A book qualifies as a deal if it meets EITHER condition:
- Current price is under $4.00, OR
- Current price is at least 50% off the list price

### Notification Rules

Users are notified when:
1. A book first meets deal criteria (first-time notification)
2. A previously notified book drops to a lower price (price drop notification)

Users are NOT notified if:
- Book doesn't meet deal criteria
- Book was already notified at the same or lower price
- This prevents duplicate notifications for the same deal

### Implementation

The logic is implemented in `src/deal_logic.py`:
- `is_deal(current_price, list_price)` - Returns True if book qualifies as a deal
- `should_notify(current_price, list_price, last_notified_price)` - Returns True if user should be notified

## Configuration

Configuration is stored in `config.yaml` (created from `config.yaml.example`).

### Configuration Sections

**amazon** - Amazon settings
- `domain`: Amazon domain (e.g., "amazon.com")

**database** - MySQL connection settings
- `host`: MySQL server host (default: "localhost")
- `user`: MySQL username (default: "root")
- `password`: MySQL password
- `database`: Database name (default: "kindle_deals")

**storage** - File storage settings
- `browser_session_path`: Directory for Playwright browser session data

**email** - SMTP email settings
- `smtp_server`: SMTP server (e.g., "smtp.mail.me.com")
- `smtp_port`: SMTP port (e.g., 587 for TLS)
- `from_address`: Sender email address
- `to_address`: Recipient email address
- `password`: Email password (app-specific password for iCloud/Gmail)
- `subject_template`: Email subject template

**deals** - Deal detection criteria
- `max_price`: Maximum price for automatic deals (default: 4.00)
- `min_discount_percent`: Minimum discount percentage (default: 50)
- `notification_cooldown_days`: Days before re-notifying about same book
- `recommendation_concurrency`: Number of parallel browser tabs for recommendation checking (default: 3)

**auto_purchase** - Auto-purchase settings (Phase 1)
- `enabled`: Auto-buy eligible tracked samples with 1-Click (default: false if section absent)
- `max_price`: Only auto-buy at or below this price (default: 5.00)
- `require_points_full_coverage`: Only buy when Rewards points cover the whole price (default: true)
- `max_purchases_per_run`: Safety cap on purchases per run (default: 5)

**scraping** - Playwright browser settings
- `headless`: Run browser in headless mode
- `page_load_timeout`: Page load timeout in milliseconds
- `element_timeout`: Element wait timeout in milliseconds
- `check_delay`: Delay between checking different books
- `action_delay`: Delay between page actions

**sync** - Library sync settings
- `collection_name`: Collection to auto-add uncollected samples to (default: "Read Me 2026")
- `early_stop_threshold`: Stop after this many consecutive known ASINs (default: 10)

## Testing

### Test Structure

Tests are located in the `tests/` directory and use pytest:

- **test_database.py** - Database module tests
  - Tests require MySQL server running
  - Uses a test database (kindle_deals_test)
  - Tests book storage, price history, and notification tracking

- **test_deal_logic.py** - Deal logic tests
  - Pure unit tests with no external dependencies
  - Tests deal criteria and notification rules

- **test_config.py** - Configuration module tests
  - Tests YAML loading and dot-notation access
  - Tests password retrieval methods

- **test_email_notifier.py** - Email notifier tests
  - Tests HTML email generation
  - Tests SMTP integration (with mocking)

### Test Requirements

- MySQL server must be running for database tests
- config.yaml must be configured with MySQL credentials
- Tests create and clean up a test database automatically
- Use pytest fixtures for setup/teardown

### Running Tests

```bash
# All tests
pytest

# Specific module
pytest tests/test_database.py

# With verbose output
pytest -v

# With coverage report
pytest --cov=src --cov-report=html
```

## Price Checking Method

The application uses web scraping (Playwright) for both collecting the book list from "My Books" and checking prices. No Amazon API credentials are required.

## Development Notes

### Adding New Features

When adding new features:
1. Write tests first (TDD approach)
2. Update config.yaml.example if new settings are needed
3. Update this CLAUDE.md file with relevant information
4. Ensure all tests pass before committing

### Code Style

- Follow PEP 8 Python style guidelines
- Use type hints for function parameters and return values
- Include docstrings for all public functions and classes
- Keep functions focused and testable

### Database Changes

When modifying the database schema:
1. Update the `_create_tables()` method in database.py
2. Update the Database Schema section in this file
3. Consider migration path for existing databases
4. Update relevant tests in test_database.py

### Common Patterns

- Use context managers for database connections
- Store all configuration including passwords in config.yaml
- Use logging for operational messages (not print statements)
- Validate configuration on startup
- Handle errors gracefully with retries where appropriate
