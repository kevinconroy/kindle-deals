# Merge Deal Scripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge `check_daily_deals.py` into `check_deals.py` so one script checks both sample book prices and daily deals, sending one combined email.

**Architecture:** Add `scrape_daily_deals` and daily deals matching logic directly into `check_deals.py`. The main flow opens one browser session, runs sample checks then daily deals checks, combines results, sends one email. `check_daily_deals.py` is deleted.

**Tech Stack:** Python 3.7, Playwright, MySQL, SimilarityMatcher

---

### Task 1: Add daily deals functions to check_deals.py

**Files:**
- Modify: `src/check_deals.py`

**Step 1: Add SimilarityMatcher import**

At the top of `src/check_deals.py`, add to the imports:

```python
from similarity_matcher import SimilarityMatcher
```

**Step 2: Copy `scrape_daily_deals` function into check_deals.py**

Add after the `scrape_book_info` function (after line 233), before `check_deals`:

```python
def scrape_daily_deals(page) -> List[str]:
    """Scrape ASINs from Amazon's daily Kindle deals page."""
    deals_url = "https://www.amazon.com/amz-books/book-deals?filters=v1%3AFORMAT%5Bkindle_edition%5D"

    logger.info("Navigating to daily deals page...")
    page.goto(deals_url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3000)

    asins = []
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

    unique_asins = list(set(asins))
    logger.info(f"Found {len(unique_asins)} unique deal ASINs")
    return unique_asins
```

**Step 3: Add `check_daily_deals_phase` function**

Add after `scrape_daily_deals`, before `check_deals`:

```python
def check_daily_deals_phase(page, db: Database, check_delay: int, dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Check today's daily deals for matches against user's interests.

    Returns list of deal dicts for matched books.
    """
    matcher = SimilarityMatcher(db)
    logger.info(f"Loaded matcher with {len(matcher.sample_authors)} authors, "
                f"{len(matcher.sample_series)} series, "
                f"{len(matcher.recommended_asins)} recommendations")

    deals_found = []
    deal_asins = scrape_daily_deals(page)
    logger.info(f"Checking {len(deal_asins)} daily deals for matches...")

    for asin in deal_asins:
        # Skip if already checked today
        if not dry_run and db.was_deal_checked_today(asin):
            logger.debug(f"Skipping {asin} - already checked today")
            continue

        # Scrape book info using the full scraper
        book_info = scrape_book_info(page, asin)

        if not book_info or book_info.get('already_owned'):
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        title = book_info.get('title')
        author = book_info.get('author', '')
        current_price = book_info.get('current_price')
        list_price = book_info.get('list_price')

        if not title:
            logger.warning(f"Could not scrape info for {asin}")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        # Check if it matches user's interests
        is_match, match_reason = matcher.is_match(asin, author, title)

        if not is_match:
            logger.debug(f"No match: {title}")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        # Check price
        if current_price is None or list_price is None:
            logger.debug(f"Skipping {title} - no price info")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        from deal_logic import is_deal
        if not is_deal(current_price, list_price):
            logger.info(f"Match but not a deal: {title} (${current_price})")
            if not dry_run:
                db.add_deal_check(asin, was_deal=False, notified=False)
            continue

        savings_percent = calculate_savings_percent(current_price, list_price)
        logger.info(f"Daily deal match: {title} - ${current_price:.2f} ({match_reason})")

        deals_found.append({
            'asin': asin,
            'title': title,
            'author': author,
            'cover_url': book_info.get('cover_url'),
            'current_price': current_price,
            'list_price': list_price,
            'savings_percent': savings_percent,
            'match_reason': match_reason
        })

        if not dry_run:
            db.add_deal_check(asin, was_deal=True, notified=True)

        time.sleep(check_delay / 1000)

    logger.info(f"Found {len(deals_found)} daily deal matches")
    return deals_found
```

**Step 4: Verify file parses**

Run: `python -c "import ast; ast.parse(open('src/check_deals.py').read()); print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add src/check_deals.py
git commit -m "feat: add daily deals functions to check_deals.py"
```

---

### Task 2: Modify check_deals to run both phases

**Files:**
- Modify: `src/check_deals.py`

**Step 1: Add `--skip-samples` and `--skip-daily` flags to argparse**

In the `main()` function, add after the `--hours` argument:

```python
    parser.add_argument('--skip-samples', action='store_true',
                        help='Skip checking sample book prices')
    parser.add_argument('--skip-daily', action='store_true',
                        help='Skip checking daily deals page')
```

**Step 2: Refactor `check_deals` to accept `skip_samples` and `skip_daily` params**

Change the `check_deals` function signature to:

```python
def check_deals(config: Config, db: Database, target_asin: str = None, force: bool = False, dry_run: bool = False, skip_samples: bool = False, skip_daily: bool = False):
```

**Step 3: Restructure the function body**

The current function opens a browser and checks sample books. Restructure so:

1. Browser opens once at the top
2. If not `skip_samples`: run existing sample book checking loop (lines 258-399 current logic)
3. If not `skip_daily` and no `target_asin`: run `check_daily_deals_phase(page, db, check_delay, dry_run)` and extend `deals_found` with results
4. After both phases, send one combined email

The email sending block (lines 401-424) stays at the end but now includes deals from both phases.

**Step 4: Update the `main()` call to pass new args**

```python
            check_deals(config, db, target_asin=args.asin, force=args.force, dry_run=args.dry_run, skip_samples=args.skip_samples, skip_daily=args.skip_daily)
```

**Step 5: Verify file parses and runs with --help**

Run: `cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_deals.py --help`
Expected: Shows `--skip-samples` and `--skip-daily` in help output

**Step 6: Commit**

```bash
git add src/check_deals.py
git commit -m "feat: merge daily deals into check_deals with --skip-samples/--skip-daily flags"
```

---

### Task 3: Delete check_daily_deals.py

**Files:**
- Delete: `src/check_daily_deals.py`

**Step 1: Delete the file**

```bash
rm src/check_daily_deals.py
```

**Step 2: Verify no imports reference it**

Run: `grep -r "check_daily_deals" src/`
Expected: No output

**Step 3: Commit**

```bash
git rm src/check_daily_deals.py
git commit -m "refactor: remove check_daily_deals.py (merged into check_deals.py)"
```

---

### Task 4: Simplify check_all_deals.sh

**Files:**
- Modify: `check_all_deals.sh`

**Step 1: Remove step 3 (daily deals) and renumber**

Replace the script body (after argument parsing) with two steps:

1. Sync library (unless `--skip-sync`) — unchanged
2. Check deals: `python src/check_deals.py $DRY_RUN $VERBOSE $FORCE`

Remove the `--skip-sync` step's daily deals invocation entirely. The header comment should say "2 steps" not "3 steps".

Add pass-through for `--skip-samples` and `--skip-daily` flags:

```bash
SKIP_SAMPLES=""
SKIP_DAILY=""
```

Add cases in the argument parser:

```bash
        --skip-samples)
            SKIP_SAMPLES="--skip-samples"
            shift
            ;;
        --skip-daily)
            SKIP_DAILY="--skip-daily"
            shift
            ;;
```

Update the check deals invocation:

```bash
python src/check_deals.py $DRY_RUN $VERBOSE $FORCE $SKIP_SAMPLES $SKIP_DAILY
```

Update the `--help` output to include the new flags.

**Step 2: Verify script runs with --help**

Run: `./check_all_deals.sh --help`
Expected: Shows all flags including `--skip-samples` and `--skip-daily`

**Step 3: Commit**

```bash
git add check_all_deals.sh
git commit -m "refactor: simplify check_all_deals.sh to use merged check_deals.py"
```

---

### Task 5: Update README.md

**Files:**
- Modify: `README.md`

**Step 1: Remove any references to check_daily_deals.py**

The current README doesn't reference it directly, but verify and ensure the usage section reflects the merged script. The README was recently rewritten and should be clean — just verify.

**Step 2: Commit (if changes needed)**

```bash
git add README.md
git commit -m "docs: update README for merged deal script"
```

---

### Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Remove check_daily_deals.py references**

Remove these lines/sections:
- Line 73: `python src/check_daily_deals.py`
- Line 76: `python src/check_daily_deals.py --dry-run`
- Line 93: cron entry for check_daily_deals.py
- Line 156: `3. **check_daily_deals.py** - Checks Amazon's daily deals for books matching your interests`

**Step 2: Update check_deals.py description**

Update the script description to mention it handles both sample books and daily deals. Add `--skip-samples` and `--skip-daily` to the documented flags.

**Step 3: Update check_all_deals.sh description**

Change from "runs sync + check daily deals" to "runs sync + check deals". Update the step list.

**Step 4: Simplify cron section**

Only show one cron example since everything runs through `check_all_deals.sh` or `check_deals.py`.

**Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for merged deal script"
```

---

### Task 7: Smoke test

**Step 1: Run dry-run to verify everything works end to end**

```bash
cd /Users/kconroy/Sites/kindle-deals && source venv/bin/activate && python src/check_deals.py --dry-run --verbose
```

Expected: Script runs both sample check and daily deals check phases, no errors.

**Step 2: Run with --skip-daily**

```bash
python src/check_deals.py --dry-run --verbose --skip-daily
```

Expected: Only runs sample book checks.

**Step 3: Run with --skip-samples**

```bash
python src/check_deals.py --dry-run --verbose --skip-samples
```

Expected: Only runs daily deals checks.

**Step 4: Run shell script**

```bash
./check_all_deals.sh --dry-run --skip-sync
```

Expected: Runs check_deals.py with both phases, no errors.
