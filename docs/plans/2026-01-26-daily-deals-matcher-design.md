# Daily Deals Matcher - Design Document

**Date:** 2026-01-26
**Status:** Approved

## Overview

Extend Kindle Deals Monitor to scrape Amazon's daily Kindle deals page and notify about deals that match the user's reading interests based on their existing sample library.

## Goals

- Discover new deals beyond just tracked samples
- Filter daily deals (50-100+ books) to only relevant matches
- Leverage Amazon's recommendation data for similarity matching
- Reuse existing email infrastructure for consistency

## Database Schema Changes

### New Table: `recommendations`

Stores Amazon's "Customers who bought X also bought Y" data.

```sql
CREATE TABLE recommendations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_asin VARCHAR(20) NOT NULL,      -- User's sample book
    recommended_asin VARCHAR(20) NOT NULL, -- Amazon's recommendation
    created_date DATETIME NOT NULL,
    FOREIGN KEY (source_asin) REFERENCES books(asin),
    UNIQUE KEY unique_recommendation (source_asin, recommended_asin)
);
```

### New Table: `deal_checks`

Tracks which daily deals have been processed to avoid duplicate notifications.

```sql
CREATE TABLE deal_checks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asin VARCHAR(20) NOT NULL,
    check_date DATE NOT NULL,
    was_deal TINYINT(1) NOT NULL,  -- Met deal criteria ($4 or 50% off)
    notified TINYINT(1) NOT NULL,  -- Sent notification about it
    UNIQUE KEY unique_daily_check (asin, check_date)
);
```

## Component 1: Enhanced Library Sync

**File:** `src/sync_library.py`

### New Function: `scrape_recommendations(page, asin: str) -> List[str]`

Scrapes "Customers who bought this item also bought" section from a book's product page.

**Implementation:**
1. Navigate to product page: `https://www.amazon.com/dp/{asin}`
2. Locate recommendation carousel (common selectors: `.similarities-widget`, `.p13n-desktop-carousel`)
3. Extract ASINs from product links
4. Return list of recommended ASINs (typically 10-20 books)

### Updated Sync Flow

```
1. Scrape sample ASINs from "My Books" page (existing)
2. Add/update books in database (existing)
3. For each active sample:
   a. Check if recommendations already exist (query by source_asin)
   b. If not, scrape "also bought" recommendations
   c. Store each recommended ASIN in recommendations table
4. Mark removed samples as inactive (existing)
```

**Optimization:** Only scrape recommendations for new samples or samples without existing recommendations. This keeps weekly syncs fast after initial build.

## Component 2: Daily Deals Scraper

**File:** `src/check_daily_deals.py`

### High-Level Flow

```
1. Navigate to today's Kindle deals page
   URL: https://www.amazon.com/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D

2. Scrape all deal book ASINs from page (handle pagination)

3. For each deal ASIN:
   a. Check if already processed today (query deal_checks by ASIN + today's date)
   b. If already processed, skip
   c. Visit product page, extract:
      - Title
      - Author
      - Series (if in title)
      - Current price
      - List price
   d. Check similarity using SimilarityMatcher
   e. Check if meets deal criteria ($4 or 50% off)
   f. If match AND deal:
      - Add to notification list
      - Record in deal_checks (was_deal=1, notified=1)
   g. If no match OR no deal:
      - Record in deal_checks (was_deal=0/1, notified=0)

4. Send email with all matched deals
```

## Component 3: Similarity Matching

**File:** `src/similarity_matcher.py`

### Class: `SimilarityMatcher`

```python
class SimilarityMatcher:
    def __init__(self, db: Database):
        """Load matching data from database into memory for fast lookups."""
        self.db = db

        # Cache sets for O(1) lookups
        self.sample_authors = set()      # All authors from active samples
        self.sample_series = set()       # All series names from active samples
        self.recommended_asins = dict()  # ASIN -> source book title

        self._load_cache()

    def is_match(self, asin: str, author: str, title: str) -> Tuple[bool, str]:
        """
        Check if deal book matches user's interests.

        Returns:
            (is_match: bool, reason: str)

        Example reasons:
            "Same author: Brandon Sanderson"
            "Same series: Mistborn"
            "Recommended from: The Way of Kings"
        """
```

### Matching Logic (Priority Order)

1. **Author Match**
   - Normalize author name (lowercase, strip whitespace)
   - Check if in `self.sample_authors` set
   - Return: `(True, f"Same author: {author}")`

2. **Series Match**
   - Extract series from title using regex patterns:
     - `"Book Title (Series Name, Book 1)"`
     - `"Book Title: Series Name Book 1"`
   - Check if series name in `self.sample_series` set
   - Return: `(True, f"Same series: {series_name}")`

3. **Recommendation Match**
   - Check if ASIN in `self.recommended_asins` dict
   - Return: `(True, f"Recommended from: {source_book_title}")`

4. **No Match**
   - Return: `(False, "")`

### Performance

Loading cache on initialization keeps per-book checks fast:
- Set membership: O(1)
- Checking 100 daily deals: ~100ms total

## Component 4: Email Notification

**File:** Extend `src/email_notifier.py`

### Reuse Existing Template

Use the same Amazon-style HTML template from existing deal notifications.

### Add Match Reason Badge

Insert below the author line:

```html
<div class="match-reason">
    ✓ Same author as your sample: The Way of Kings
</div>
```

**CSS:**
```css
.match-reason {
    font-size: 13px;
    color: #067d62;
    margin: 8px 0;
    font-weight: 600;
}
```

### Email Subject

Format: `"Kindle Daily Deals - {count} matches - {date}"`

Example: `"Kindle Daily Deals - 5 matches - 2026-01-26"`

### Email Structure

```
📚 Today's Kindle Deals - 5 Matches

The following books from today's deals match your reading interests:

[Book Card with Amazon styling]
- Cover image
- Title (linked)
- Author
- Match reason badge (✓ Same author: ...)
- Current price / List price / Savings
- Buy now button

[Repeat for each matched deal]
```

## Operational Details

### Cron Schedule

**Option 1: Separate timing**
```bash
# Daily deals at 5 AM
0 5 * * * cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_daily_deals.py

# Sample checks at 6 AM
0 6 * * * cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_deals.py
```

**Option 2: Sequential**
```bash
# Run both at 6 AM - daily deals first, then samples
0 6 * * * cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_daily_deals.py && python src/check_deals.py
```

### Error Handling

1. **Rate Limiting**
   - 2-3 second delay between scraping each deal book
   - Prevents triggering Amazon's anti-bot measures

2. **CAPTCHA Detection**
   - Check for CAPTCHA on page load
   - If detected: log error, skip remaining deals, exit gracefully
   - Same logic as existing `check_deals.py`

3. **Missing Data**
   - If can't extract author/series: skip book, continue processing
   - Log warning for debugging

4. **Empty Results**
   - If no matches found: don't send email (or send summary: "Checked 50 deals, no matches")
   - User preference TBD

5. **Database Failures**
   - Log error
   - Send alert email to user
   - Exit with error code

### Logging

- Use same logger as `check_deals.py`
- Prefix messages with `[DAILY_DEALS]` for clarity
- Log level: INFO for matches, DEBUG for skips, ERROR for failures

Example:
```
2026-01-26 05:00:00 [DAILY_DEALS] INFO - Checking 73 books from today's deals
2026-01-26 05:01:15 [DAILY_DEALS] INFO - Match found: Mistborn (same author: Brandon Sanderson)
2026-01-26 05:05:42 [DAILY_DEALS] INFO - Found 5 matching deals, sending notification
```

## Implementation Phases

### Phase 1: Database & Recommendation Builder
1. Add new database tables via `database.py`
2. Extend `sync_library.py` with recommendation scraping
3. Test: Run sync on small sample set, verify recommendations stored

### Phase 2: Similarity Matcher
1. Create `similarity_matcher.py` module
2. Implement caching and matching logic
3. Test: Unit tests for author/series/recommendation matching

### Phase 3: Daily Deals Scraper
1. Create `check_daily_deals.py` script
2. Implement scraping and similarity checking
3. Test: Dry run against live deals page

### Phase 4: Email Integration
1. Extend `email_notifier.py` with match reason badge
2. Wire up daily deals email generation
3. Test: Send test email with sample matches

### Phase 5: Deployment
1. Add cron job
2. Monitor first week for errors
3. Tune delays/selectors as needed

## Future Enhancements (Out of Scope)

- Genre/category filtering
- Price threshold preferences (only notify if < $3)
- ML-based similarity (beyond simple author/series/recommendations)
- Multi-user support (different users, different preferences)

## Success Criteria

- Daily deals scraping runs reliably without CAPTCHA blocks
- Recommendation database builds successfully during weekly sync
- Match detection accurately identifies relevant books
- Email notifications arrive daily with 0-10 relevant matches (not 50+)
- System runs automatically via cron with minimal maintenance
