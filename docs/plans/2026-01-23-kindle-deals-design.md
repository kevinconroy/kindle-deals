# Kindle Deals Monitor Design

**Date:** 2026-01-23
**Purpose:** Monitor Kindle samples for price deals and send email notifications

## Overview

A Python-based system that tracks Kindle books you've sampled and notifies you via email when they go on sale. The system runs locally with scheduled tasks, requiring zero cloud costs.

**Deal Criteria:**
- Price under $4.00, OR
- At least 50% off list price

**Notification Strategy:**
- Notify once when a book first meets deal criteria
- Notify again only if the price drops further

## System Architecture

### Core Components

**1. Sample Collector (`collect_samples.py`)**
- Uses Playwright to log into Amazon and navigate to "My Books"
- Filters for Kindle Samples
- Extracts book metadata: title, ASIN, author, cover image URL
- Stores samples in SQLite database

**2. Deal Checker (`check_deals.py`)**
- Iterates through all tracked samples
- Scrapes current Kindle price and list price for each book
- Evaluates deal criteria: price < $4 OR discount >= 50%
- Updates price history in database
- Triggers email notification for new deals or price drops

**3. Email Notifier (`send_notification.py`)**
- Generates HTML email with book details
- Embeds cover image
- Includes Amazon purchase link
- Sends via SMTP (Gmail, etc.)

### Database Schema (SQLite)

**books table:**
- ASIN (primary key)
- title
- author
- cover_url
- date_added
- is_active (boolean)

**price_history table:**
- id (primary key)
- ASIN (foreign key)
- price
- list_price
- check_date

**notifications table:**
- id (primary key)
- ASIN (foreign key)
- notified_price
- notified_date

### Scheduling

- Sample collection: Weekly (Sundays at 6 AM)
- Deal checking: Daily (7 AM)

## Data Flow

### Sample Collection Flow

1. Playwright launches Chrome with persistent context (saves login session)
2. First run: User manually logs into Amazon, session saved
3. Subsequent runs: Reuses saved session, no login needed
4. Navigates to amazon.com/myk (My Books)
5. Filters to show only Samples
6. Scrolls/paginates to load all samples
7. For each sample: extracts ASIN, title, author, cover URL
8. Compares with database: adds new samples, marks removed ones as inactive

### Deal Detection Flow

1. Script fetches all active samples from database
2. For each book:
   - Scrapes product page (amazon.com/dp/{ASIN})
   - Extracts current Kindle price and list price
   - Stores in price_history table
   - Compares with previous price check
3. Evaluates notification logic
4. For qualifying deals, queues email notification

### Notification Decision Logic

```python
def should_notify(current_price, list_price, last_notified_price):
    is_deal = (current_price < 4.00) or (current_price <= list_price * 0.5)

    if not is_deal:
        return False

    if last_notified_price is None:
        return True  # First time deal

    if current_price < last_notified_price:
        return True  # Price dropped further

    return False
```

## Error Handling

### Authentication & Session Management
- If session expires: Log warning, exit with error code (cron will retry next day)
- On first run: Detect no saved session, launch visible browser for manual login
- Session file location: `~/.kindle-deals/browser-session/`

### Scraping Failures
- Individual book scraping fails: Log error, continue with next book
- Amazon rate limiting detected: Implement exponential backoff (1s, 2s, 4s delays)
- Page structure changes: Catch parsing errors, log detailed HTML snippet for debugging
- Network errors: Retry up to 3 times with 5-second delays

### Email Delivery
- SMTP failures: Log error, save failed notifications to retry queue
- Invalid/missing config: Fail fast with clear error message on first run
- Rate limits (Gmail 500/day): Track daily send count, warn if approaching limit

### Data Integrity
- Missing prices: Don't trigger notifications, log as "price unavailable"
- Invalid ASINs: Mark as inactive after 3 consecutive failures
- Database corruption: Keep daily backups of SQLite file

### Edge Cases
- Book no longer available: Mark as inactive, don't notify
- Free books ($0.00): Count as deal, notify once
- Pre-orders with no price: Skip until price available
- Kindle Unlimited books: Track KU availability separately, notify if both on sale AND available

## Configuration

### Configuration File (`config.yaml`)

```yaml
amazon:
  domain: amazon.com  # Support different regions
  sample_check_frequency: weekly
  deal_check_frequency: daily

notifications:
  email:
    smtp_server: smtp.gmail.com
    smtp_port: 587
    from_address: your-email@gmail.com
    to_address: your-email@gmail.com
    password_source: env  # Read from KINDLE_DEALS_PASSWORD env var

deal_criteria:
  max_price: 4.00
  min_discount_percent: 50

storage:
  database_path: ~/.kindle-deals/deals.db
  browser_session_path: ~/.kindle-deals/browser-session
  backup_enabled: true
  backup_retention_days: 30

scraping:
  headless: true  # Set to false for debugging
  page_timeout: 30
  retry_attempts: 3
  delay_between_requests: 2  # seconds
```

### Project Structure

```
kindle-deals/
├── README.md
├── requirements.txt
├── setup.py
├── config.yaml
├── src/
│   ├── collect_samples.py
│   ├── check_deals.py
│   ├── send_notification.py
│   ├── database.py (shared DB helpers)
│   └── scraper.py (shared scraping utilities)
└── tests/
    └── test_deal_logic.py
```

## Testing & Execution

### Testing Strategy

**Unit Tests** (`tests/test_deal_logic.py`):
- Deal criteria evaluation (price/discount thresholds)
- Notification decision logic
- Database operations (CRUD for books, price history)

**Manual Testing Commands**:
```bash
# Test sample collection (dry-run mode)
python src/collect_samples.py --dry-run

# Test deal checking for specific book
python src/check_deals.py --asin B01234ABCD --verbose

# Test email notification
python src/send_notification.py --test
```

**Debugging Mode**:
- Set `headless: false` in config to watch browser
- `--verbose` flag shows detailed scraping steps
- Logs written to `~/.kindle-deals/logs/`

### Running the System

**Initial Setup**:
```bash
pip install -r requirements.txt
playwright install chromium
python setup.py
```

**Manual Runs** (for testing):
```bash
python src/collect_samples.py
python src/check_deals.py
```

**Scheduled Runs** (cron entries):
```bash
# Weekly sample collection (Sundays at 6 AM)
0 6 * * 0 cd /path/to/kindle-deals && python src/collect_samples.py

# Daily deal check (7 AM)
0 7 * * * cd /path/to/kindle-deals && python src/check_deals.py
```

### Monitoring

- Logs include: books checked, deals found, emails sent, errors
- Weekly summary email: X samples tracked, Y deals found this week
- Exit codes: 0=success, 1=partial failure, 2=critical failure

## Future Enhancements

- CloudFormation deployment for AWS Lambda execution
- Web dashboard for viewing deal history
- Price history charts in email notifications
- Support for tracking non-sample books
- Multiple notification channels (SMS, push notifications)
