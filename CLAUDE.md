# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kindle Deals Monitor is a Python application that tracks price changes on Kindle books in your "My Books" library and sends email notifications when deals are found. The application uses Amazon's Product Advertising API for price checking and web scraping (via Playwright) to collect your book list from Amazon's "My Books" page.

## Quick Start Commands

### Development Setup
```bash
# Install dependencies
pip install -e .

# Set required environment variables
export MYSQL_PASSWORD="your-mysql-password"
export KINDLE_DEALS_PASSWORD="your-email-password"

# Copy and configure settings
cp config.yaml.example config.yaml
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
```bash
# Collect books from Amazon "My Books" page
python src/collect_samples.py

# Check for deals on tracked books
python src/check_deals.py

# Check specific book by ASIN
python src/check_deals.py --asin B01234567X

# Send test email notification
python src/send_notification.py
```

## Architecture

### Core Modules

The application consists of five main modules:

1. **database.py** - MySQL database interface
   - Uses mysql-connector-python for MySQL connections
   - Manages three tables: books, price_history, notifications
   - Auto-creates database and tables on initialization
   - Provides methods for adding/retrieving books, prices, and notifications

2. **deal_logic.py** - Deal detection logic
   - Pure functions with no dependencies
   - Implements deal criteria ($4 and 50% rules)
   - Determines when notifications should be sent

3. **config.py** - Configuration management
   - Loads settings from config.yaml
   - Provides dot-notation access (e.g., config.get("amazon.domain"))
   - Loads passwords from environment variables (MYSQL_PASSWORD, KINDLE_DEALS_PASSWORD)
   - Validates required settings

4. **email_notifier.py** - Email notification system
   - Sends HTML emails via SMTP
   - Generates formatted deal notifications with book covers
   - Supports Gmail SMTP (configurable)

5. **scraper.py** - Web scraping utilities for "My Books"
   - Uses Playwright for browser automation
   - Provides session persistence for authenticated scraping
   - Contains helper functions for price extraction
   - NOTE: Only used for collecting book list, not for price checking

### Scripts

1. **collect_samples.py** - Collects books from Amazon "My Books" page using Playwright
2. **check_deals.py** - Checks book prices via Product Advertising API and sends notifications
3. **send_notification.py** - Sends test email notifications

## Database Schema

The application uses MySQL with three tables:

### books table
```sql
CREATE TABLE books (
    asin VARCHAR(20) PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(255),
    cover_url VARCHAR(1000),
    date_added DATETIME NOT NULL,
    is_active TINYINT(1) DEFAULT 1
)
```

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
- `check_frequency`: How often to check prices (seconds)
- `daily_check_time`: Preferred time for daily checks
- `api_access_key`: Product Advertising API access key
- `api_secret_key`: Product Advertising API secret key
- `api_associate_tag`: Amazon Associates tag
- `api_region`: API region (US, UK, FR, DE, JP, etc.)

**database** - MySQL connection settings
- `host`: MySQL server host (default: "localhost")
- `user`: MySQL username (default: "root")
- `database`: Database name (default: "kindle_deals")
- Password loaded from MYSQL_PASSWORD environment variable

**storage** - File storage settings
- `browser_session_path`: Directory for Playwright browser session data

**email** - SMTP email settings
- `smtp_host`: SMTP server (e.g., "smtp.gmail.com")
- `smtp_port`: SMTP port (e.g., 587 for TLS)
- `from_address`: Sender email address
- `to_addresses`: List of recipient email addresses
- Password loaded from KINDLE_DEALS_PASSWORD environment variable
- `subject_template`: Email subject template

**deals** - Deal detection criteria
- `max_price`: Maximum price for automatic deals (default: 4.00)
- `min_discount_percent`: Minimum discount percentage (default: 50)
- `notification_cooldown_days`: Days before re-notifying about same book

**scraping** - Playwright browser settings (for "My Books" collection only)
- `headless`: Run browser in headless mode
- `page_load_timeout`: Page load timeout in milliseconds
- `element_timeout`: Element wait timeout in milliseconds
- `check_delay`: Delay between checking different books
- `action_delay`: Delay between page actions

### Environment Variables

Two environment variables must be set:

1. **MYSQL_PASSWORD** - Password for MySQL database connection
2. **KINDLE_DEALS_PASSWORD** - Password for email SMTP authentication

These are loaded by the Config class and should never be stored in config.yaml.

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
  - Tests environment variable integration

- **test_email_notifier.py** - Email notifier tests
  - Tests HTML email generation
  - Tests SMTP integration (with mocking)

### Test Requirements

- MySQL server must be running for database tests
- MYSQL_PASSWORD environment variable must be set
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

**IMPORTANT**: The application uses Amazon's Product Advertising API for price checking, NOT web scraping.

- Price checking is done via the paapi5-python-sdk library
- Requires API credentials from Amazon Associates program
- Web scraping (Playwright) is ONLY used to collect the book list from "My Books"
- This hybrid approach provides reliable price data while still tracking your personal library

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
- Load sensitive data from environment variables
- Use logging for operational messages (not print statements)
- Validate configuration on startup
- Handle API errors gracefully with retries where appropriate
