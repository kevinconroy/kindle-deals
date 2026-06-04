# Auto-Purchase Eligible Samples With Points — Design

**Date:** 2026-06-04
**Status:** Approved (pending spec review)

## Goal

When the deal checker finds that a book we have a **sample** of is on sale, and we
have enough Amazon Rewards Visa Card points to pay for it entirely, automatically
buy it with 1-Click (applying the points), and tell the user in the daily email
that it was auto-purchased.

## Scope decisions (confirmed with user)

- **Trigger scope:** *Exact sample only.* Auto-buy only when the on-sale ASIN is
  literally a book we have a sample of (`books.is_sample = 1`, `is_deleted = 0`).
  Same-author / same-series / recommendation matches do **not** trigger a purchase.
- **Safety model:** On by default (runs as part of the normal workflow), gated by a
  config toggle and guardrails described below.
- **Points rule:** Points must **fully cover** the price (purchase costs $0 cash).
- **Price cap:** Only when `current_price <= auto_purchase.max_price` (default $5.00).

## Where it lives

The hook lives in **Phase 1** of `check_deals.py` (the sample price-check loop),
which already loads each sample's product page and computes price / deal status.
Phase 1 visits every active sample daily, so a sample that also appears on the
daily-deals page is already covered here. **No change to the Phase 2 matcher.**

## Eligibility — all conditions must hold

1. Book is a tracked sample (`is_sample = 1`, `is_deleted = 0`) — guaranteed in Phase 1.
2. `is_deal(current_price, list_price)` is true (existing logic in `deal_logic.py`).
3. `current_price <= auto_purchase.max_price` (default $5.00).
4. Not already owned (no "Read Now" signal — existing `already_owned` detection).
5. **Points cover the price.** Parse the buy-box checkbox label
   `Use $X.XX (N points) of Amazon Rewards Visa Card points`. When
   `auto_purchase.require_points_full_coverage` is true (the default), eligible
   only if the parsed `$X.XX >= current_price`; Amazon displays
   `min(balance, price)`, so a partial balance shows less than the price and is
   correctly rejected. When the toggle is false, the checkbox merely needs to be
   present (some points available).
6. Not already recorded in the `purchases` table (idempotency).
7. Under the per-run cap `auto_purchase.max_purchases_per_run` (default 5).

## Purchase mechanics — new module `src/purchaser.py`

A single well-bounded function:

```
attempt_purchase(page, asin, current_price, action_delay) -> dict
    returns {"success": bool, "points_applied": float | None, "reason": str}
```

Steps:

1. Locate the points checkbox `#balance-checkbox-0`. If absent → return
   `success=False, reason="no points checkbox"`.
2. Parse its label dollar amount. If `amount < current_price` → return
   `success=False, reason="points do not fully cover"`.
3. Check **only** `#balance-checkbox-0`. **Never** touch `#narration-checkbox`
   (the "Add audiobook for $X" option sits right beside it). Verify it reports
   checked after the click.
4. Capture a "before" screenshot to the session directory.
5. Click `#one-click-button` (value "Buy now with 1-Click",
   name `submit.one-click-order.x`).
6. Confirm the order: wait for a post-order success signal — order-confirmation
   text ("Thank you" / "order has been placed") and/or the appearance of a
   "Read Now" / `#kindle-reader-button`. Capture an "after" screenshot.
7. Only a confirmed order returns `success=True` with `points_applied = amount`.

Keeping the DOM-mutating logic isolated keeps `check_deals.py` readable and lets
the purchaser be unit-tested with a mocked Playwright page.

### Known, unavoidable risk

1-Click places the order **instantly with no review page**. We cannot verify that
"tick `#balance-checkbox-0` → click 1-Click" actually applies the points to the
order without making a real purchase. The code confirms the *order was placed*;
"points were applied" remains an assumption until observed live. Mitigations:
before/after screenshots per purchase, and the user watches the first real run.

## Database changes

New table:

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

New methods in `database.py`:
- `add_purchase(asin, price, points_applied)` — insert (idempotent via UNIQUE).
- `is_purchased(asin) -> bool` — eligibility guard.

### Write timing (split for safety)

- **Immediately after a confirmed purchase:** `add_purchase(...)`. This is what
  prevents ever double-buying, so it must not wait for the email.
- **After the email is sent:** `mark_book_deleted(asin)` for each purchased ASIN,
  so we stop tracking the now-owned book. This honors the "after the email"
  requirement.

## Email changes (`email_notifier.py`)

The deal dict gains an optional `auto_purchased: bool` (and `points_applied`).
In `_generate_book_html`, when `auto_purchased` is true:
- Render a green **"Auto-purchased"** badge (reuse the existing badge styling
  pattern, e.g. like `.savings` / `.price-drop`).
- Replace the "Buy now on Amazon" button with a **"Read now"** link.

Auto-purchased books still appear in the **Tracked Deals** section and still get a
normal notification record (`add_notification`).

## Control flow in Phase 1

After existing per-book logic computes `current_price`, `list_price`, deal status,
and confirms not-owned, and before/around the notification block:

```
if auto_purchase.enabled
   and is_deal(...)
   and current_price <= auto_purchase.max_price
   and not db.is_purchased(asin)
   and run_purchase_count < auto_purchase.max_purchases_per_run:
       result = purchaser.attempt_purchase(page, asin, current_price, action_delay)
       if result["success"]:
           db.add_purchase(asin, current_price, result["points_applied"])   # immediate
           run_purchase_count += 1
           deal["auto_purchased"] = True
           deal["points_applied"] = result["points_applied"]
           purchased_asins.append(asin)   # for post-email untrack
```

The book is still appended to `tracked_deals` and still recorded via
`add_notification` (within the existing batch write). Dry-run (`--dry-run`) skips
the purchase entirely (logs "would auto-purchase").

After the email send block in `check_deals(...)`:

```
for asin in purchased_asins:
    db.mark_book_deleted(asin)
```

## Config (new section in `config.yaml` / `config.yaml.example`)

```yaml
auto_purchase:
  enabled: true
  max_price: 5.00
  require_points_full_coverage: true
  max_purchases_per_run: 5
```

Read via `config.get('auto_purchase.enabled', False)` etc. Default to safe values
when the section is absent (treat `enabled` as False if unset).

## Testing

- `tests/test_purchaser.py` — unit tests with a mocked Playwright page object:
  - points label parsing (full cover / partial / absent),
  - checkbox-checked verification path,
  - confirmation-signal success vs. failure,
  - never selecting `#narration-checkbox`.
- `tests/test_database.py` — `add_purchase` / `is_purchased` round-trip and
  idempotency (UNIQUE constraint).
- `tests/test_email_notifier.py` — `auto_purchased` badge + "Read now" rendering;
  absence of badge when flag unset (backward compatibility).
- Deal-logic guard combinations (price cap, points coverage) as pure-ish checks.

## Out of scope

- Buying based on author/series/recommendation matches.
- Partial-points purchases (cash + points).
- Separate points-balance API lookup (we rely on the buy-box label).
- Refund/return handling.
