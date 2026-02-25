# Recommended Deals Feature Design

**Date:** 2026-02-25
**Status:** Approved

## Problem

The `recommendations` table stores 500+ ASINs from Amazon's "customers also bought" carousels, but they're only used as a filter when matching against Amazon's daily deals page. The system never proactively checks prices for recommended books. A recommended book only surfaces as a deal if Amazon independently puts it on their daily deals page that day.

## Solution

Add a new Phase 3 to `check_deals.py` that proactively scrapes prices for all recommended ASINs using parallel Playwright tabs, then shows qualifying deals in a separate "Recommended Deals" email section.

## Design

### Parallel Scraping (Phase 3 in check_deals.py)

- Check **all** recommended ASINs each run (no batching/rotation)
- Use **3 concurrent Playwright tabs** in a `ThreadPoolExecutor`, sharing the same browser context (session cookies)
- Concurrency configurable via `deals.recommendation_concurrency` (default: 3)
- Skip ASINs already checked today (via `deal_checks` table)
- Reuse existing `scrape_book_info()` function for each ASIN
- Add newly discovered books to the `books` table with `is_recommendation=1`
- Run standard `should_notify()` logic using `price_history` and `notifications` tables
- Record each check in `deal_checks` to prevent rechecking on reruns
- Collect qualifying deals into a separate `recommended_deals` list

### Database Schema Changes

**One new column on `books` table:**
```sql
ALTER TABLE books ADD COLUMN is_recommendation TINYINT(1) DEFAULT 0;
```

Distinguishes recommendation-origin books from the user's library. The `_create_tables` method includes this column; existing books default to `0`.

**No new tables.** Reuses: `books`, `price_history`, `notifications`, `deal_checks`.

**New database methods:**
- `get_unchecked_recommendation_asins()` - returns all unique `recommended_asin` values from `recommendations` table not yet checked today (via `deal_checks`)
- `add_recommendation_book(asin, title, author, cover_url)` - adds to `books` with `is_recommendation=1`, or updates info if already exists
- `get_recommendation_source(asin)` - returns the source sample book title for a recommended ASIN (for match_reason in email)

### Email Structure

**Section 1: "Tracked Deals"**
- Contains sample book deals (Phase 1) + daily deal matches (Phase 2), same as today
- If empty, shows "No tracked deals today" message instead of omitting the section

**Section 2: "Recommended Deals"**
- Contains deals found from proactive recommendation checking (Phase 3)
- Each book shows: price, list price, savings %, cover image, buy link, plus match reason (which sample book led to this recommendation)
- If empty, this section is omitted entirely

**Send rules:**
- Send email if either section has deals
- If both are empty, no email (same as today)
- If Section 1 is empty but Section 2 has deals, Section 1 shows "No tracked deals today" and Section 2 shows deals

### Notification Rules

Same as sample books:
- Track notifications in `notifications` table
- Only notify once per price level
- Re-notify only when price drops further
- Uses existing `should_notify()` from `deal_logic.py`

### Configuration

New config.yaml entries under `deals`:
```yaml
deals:
  recommendation_concurrency: 3  # number of parallel Playwright tabs
```

### CLI Flags

New flag for `check_deals.py` and `check_all_deals.sh`:
- `--skip-recommendations` - skip Phase 3 (recommendation price checking)

## Files Modified

- `src/database.py` - new column, new query methods
- `src/check_deals.py` - new Phase 3 with parallel scraping
- `src/email_notifier.py` - two-section email template
- `src/deal_logic.py` - no changes (reused as-is)
- `config.yaml.example` - new config entries
- `check_all_deals.sh` - new `--skip-recommendations` flag
- `tests/` - new tests for recommendation checking and email sections
