# Sync Library Redesign

## Summary

Three changes to `sync_library.py`:
1. Switch from `booksSamples` to `booksAll` URL and distinguish owned books from samples
2. Early-stop optimization: stop syncing after 10 consecutive known ASINs (unless `--force`)
3. Auto-add uncollected samples to a configurable collection (e.g., "Read Me 2026")

## Database Changes

### Rename `is_active` to `is_sample`
- `ALTER TABLE books CHANGE is_active is_sample TINYINT(1) DEFAULT 1`
- Existing books (all samples) keep value `1`
- Owned books discovered on `booksAll` page get `is_sample = 0`

### Add `is_deleted` column
- `ALTER TABLE books ADD COLUMN is_deleted TINYINT(1) DEFAULT 0`
- Set to `1` when a book disappears from the library during a `--force` full sync
- Replaces the old `mark_book_inactive()` functionality

### Method renames
- `get_active_books()` -> `get_sample_books()`: filter `WHERE is_sample = 1 AND is_deleted = 0`
- `mark_book_inactive()` -> `mark_book_deleted()`
- `reactivate_book()` -> `undelete_book()`
- `add_book()` gains `is_sample` parameter (default `True`)

## Sync Flow (Single-Pass)

**URL:** `https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc/`

Per page (25 items):

1. **Parse items:** Extract ASIN from div id, check for "Sample" label above title. No label = owned (`is_sample=0`).

2. **Early-stop:** Track consecutive known ASINs. If >= 10 consecutive and not `--force`, stop syncing. Reset counter on any new ASIN.

3. **Collection management:** Identify samples with 0 collections. If any found, batch-select them (checkboxes), click "Add to Collections", pick the configured collection. One batch operation per page.

4. **Save to DB:** `add_book()` with `is_sample` flag. Update `is_sample` for existing books if status changed (e.g., user purchased a sample).

## Configuration

New settings in `config.yaml`:

```yaml
sync:
  collection_name: "Read Me 2026"
  early_stop_threshold: 10
```

## CLI Flags

New flags on `sync_library.py`:
- `--force`: Disable early stopping, scrape all pages
- `--skip-collections`: Skip collection management step

Pass-through in `check_all_deals.sh`:
- `--force` already exists, will be forwarded to sync

## Error Handling

- Collection management failures log warnings but don't break ASIN sync
- If configured collection doesn't exist in dropdown, log error with available options and skip
- Removal tracking (`is_deleted`) only runs during `--force` full syncs (early-stop means incomplete library view)

## Page Element Detection

Selectors need to be determined by inspecting the live `booksAll` page:
- Sample label: text element near `.digital_entity_title` containing "Sample"
- Collection count: text like "0 Collections" near each item
- Checkboxes: `<input type="checkbox">` near each item row
- "Add to Collections" button: toolbar area, active when items checked

These will be finalized during implementation by inspecting the actual DOM.

## Impact on Other Modules

- `check_deals.py`: Update to use `get_sample_books()` instead of `get_active_books()`
- `check_all_deals.sh`: Forward `--force` to sync, add `--skip-collections` option
- `CLAUDE.md`: Update database schema docs, CLI flags, architecture notes
- Tests: Update `test_database.py` for renamed columns/methods
