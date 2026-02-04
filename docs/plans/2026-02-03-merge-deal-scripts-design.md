# Merge Deal Scripts Design

## Goal

Combine `check_deals.py` and `check_daily_deals.py` into a single script that checks both sample book prices and daily deals in one run, sending one combined email.

## Changes

### check_deals.py — Merge in daily deals logic

New CLI flags:
- `--skip-samples` — Skip checking sample book prices
- `--skip-daily` — Skip checking daily deals page

Default: both run. Existing flags unchanged (`--dry-run`, `--force`, `--asin`, `--verbose`, `--send-notification`).

Main flow:
1. Setup (config, db, browser session opened once)
2. If not `--skip-samples`: check sample books (existing logic)
3. If not `--skip-daily`: scrape deals page → filter through SimilarityMatcher → scrape prices on matches using full `scrape_book_info`
4. Combine all deals into one list
5. Send one email
6. Cleanup

Move `scrape_daily_deals` function (deals page ASIN scraper) into check_deals.py. Use the existing full `scrape_book_info` for both phases. Add `match_reason` field to deal dicts from daily deals phase.

Import `SimilarityMatcher` for the daily deals phase.

### check_daily_deals.py — Delete

All logic absorbed into check_deals.py.

### check_all_deals.sh — Simplify

Remove step 3 (daily deals check). The script becomes:
1. Sync library (unless `--skip-sync`)
2. Run `check_deals.py` (handles both samples and daily deals)

Pass through `--skip-samples` and `--skip-daily` flags if needed.

### README.md — Update

- Remove references to `check_daily_deals.py`
- Update usage examples to reflect merged script

### CLAUDE.md — Update

- Remove `check_daily_deals.py` from scripts list and architecture docs
- Update command examples
- Document new `--skip-samples` / `--skip-daily` flags
