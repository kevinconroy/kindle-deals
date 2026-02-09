# Email Template Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore "last known price" display in deal emails, improve the buy button styling, and polish the overall email layout.

**Architecture:** All changes are in `src/email_notifier.py` (HTML/CSS template) and `src/check_deals.py` (data passing for daily deals). The email uses inline-friendly CSS with table-based layout for email client compatibility.

**Tech Stack:** Python, HTML email templates, pytest

---

### Task 1: Add previous_price to daily deals data

Daily deals (from `check_deals.py:328-337`) don't pass `previous_price` to the email template, unlike sample books which do. We need to look up the previous price for daily deals too.

**Files:**
- Modify: `src/check_deals.py:328-337`
- Test: `tests/test_email_notifier.py`

**Step 1: Add previous_price lookup for daily deals**

In `src/check_deals.py`, the daily deals section builds a dict at lines 328-337. Before that block, add a lookup and include it in the dict:

```python
# Around line 325, before the deals_found.append:
previous_price = db.get_previous_price(asin) if db.get_book(asin) else None

deals_found.append({
    'asin': asin,
    'title': title,
    'author': author,
    'cover_url': book_info.get('cover_url'),
    'current_price': current_price,
    'list_price': list_price,
    'previous_price': previous_price,
    'savings_percent': savings_percent,
    'match_reason': match_reason
})
```

Note: `get_previous_price` requires the ASIN to exist in the books table (foreign key on price_history). Daily deals may reference external books not in the user's library, so guard with `db.get_book(asin)`.

**Step 2: Run existing tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add src/check_deals.py
git commit -m "feat: pass previous_price for daily deals to email template"
```

---

### Task 2: Polish email CSS - buy button, typography, spacing

**Files:**
- Modify: `src/email_notifier.py` (CSS block, lines 42-160)
- Test: `tests/test_email_notifier.py`

**Step 1: Update the CSS styles**

Replace the entire `<style>` block (lines 46-160) with:

```css
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #ff9900;
            border-bottom: 2px solid #ff9900;
            padding-bottom: 10px;
            font-size: 24px;
            margin-bottom: 5px;
        }
        .book {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin: 16px 0;
            background-color: #ffffff;
        }
        .book-content {
            display: table;
            width: 100%;
        }
        .book-cover {
            display: table-cell;
            vertical-align: top;
            width: 120px;
            padding-right: 20px;
        }
        .book-cover img {
            max-width: 120px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.12);
        }
        .book-details {
            display: table-cell;
            vertical-align: top;
        }
        .book-title {
            font-size: 18px;
            font-weight: bold;
            color: #232f3e;
            margin: 0 0 4px 0;
            line-height: 1.3;
        }
        .book-author {
            font-size: 14px;
            color: #555;
            margin: 0 0 10px 0;
        }
        .price-info {
            margin: 10px 0;
        }
        .current-price {
            font-size: 22px;
            font-weight: bold;
            color: #b12704;
        }
        .list-price {
            font-size: 14px;
            color: #888;
            text-decoration: line-through;
            margin-left: 8px;
        }
        .savings {
            display: inline-block;
            background-color: #c45500;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }
        .previous-price {
            font-size: 13px;
            color: #888;
        }
        .price-drop {
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }
        .buy-button {
            display: inline-block;
            background-color: #ff9900;
            color: #ffffff;
            padding: 10px 24px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            margin-top: 12px;
            letter-spacing: 0.3px;
        }
        .buy-button:hover {
            background-color: #ec8a00;
        }
        .buy-button:active {
            color: #ffffff;
        }
        .match-reason {
            font-size: 13px;
            color: #067d62;
            margin: 6px 0 10px 0;
            font-weight: 600;
            padding: 4px 0;
        }
        .match-reason::before {
            content: "✓ ";
            font-weight: bold;
        }
    </style>
```

Key changes:
- **Buy button**: `color: #ffffff` (white text) instead of `#111`, larger border-radius (6px), slightly more padding, added `:active` state with white text
- **Body**: system font stack, light gray background so white cards pop
- **Book cards**: white background instead of #f9f9f9, slightly tighter margins (16px)
- **Cover images**: slightly smaller (120px), deeper shadow
- **Title**: slightly smaller (18px vs 20px), tighter line-height
- **Price**: slightly smaller (22px vs 24px) - still prominent but less shouty
- **Overall**: tighter spacing, more refined feel

**Step 2: Run tests to verify no regressions**

Run: `pytest tests/test_email_notifier.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add src/email_notifier.py
git commit -m "style: polish email template - white buy button text, refined spacing"
```

---

### Task 3: Improve previous price display

Currently, the previous price only shows when there's a price *drop* from the last check. We want to always show the last known price when available, even if the price hasn't changed or went up (helps show context for how good the deal is).

**Files:**
- Modify: `src/email_notifier.py` (lines 250-257, the previous price display section)
- Test: `tests/test_email_notifier.py`

**Step 1: Write a failing test for previous_price display without price drop**

Add to `tests/test_email_notifier.py`:

```python
def test_generate_email_html_shows_previous_price():
    """Test that previous price is shown even without a price drop."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'Test Book',
            'author': 'Test Author',
            'cover_url': 'https://example.com/cover.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
            'previous_price': 2.99,  # Same price - no drop
        }
    ]

    html = EmailNotifier.generate_email_html(books)
    assert 'Last seen' in html
    assert '$2.99' in html
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_email_notifier.py::test_generate_email_html_shows_previous_price -v`
Expected: FAIL (currently "Last seen" text doesn't exist)

**Step 3: Update the previous price display logic**

In `src/email_notifier.py`, replace the previous price section (lines 250-257) with logic that always shows the previous price when available, and adds a price drop badge only when there's an actual drop:

Replace:
```python
            # Show previous price and price drop if available
            if previous_price and price_drop and price_drop > 0:
                html += f"""
                    <div style="font-size: 13px; color: #555;">
                        <span class="previous-price">Was: ${previous_price:.2f}</span>
                        <span class="price-drop">↓ ${price_drop:.2f} ({price_drop_percent}%)</span>
                    </div>
"""
```

With:
```python
            # Show previous price when available
            if previous_price is not None and previous_price > 0:
                html += f"""
                    <div style="font-size: 13px; color: #888; margin-top: 4px;">
                        <span class="previous-price">Last seen: ${previous_price:.2f}</span>
"""
                if price_drop and price_drop > 0:
                    html += f"""
                        <span class="price-drop">↓ ${price_drop:.2f} ({price_drop_percent}%)</span>
"""
                html += """
                    </div>
"""
```

**Step 4: Run all tests to verify**

Run: `pytest tests/test_email_notifier.py -v`
Expected: All PASS including new test

**Step 5: Commit**

```bash
git add src/email_notifier.py tests/test_email_notifier.py
git commit -m "feat: always show last known price in deal emails"
```

---

### Task 4: Polish intro text and footer

**Files:**
- Modify: `src/email_notifier.py` (header/footer HTML)

**Step 1: Update intro and footer**

Replace the intro paragraph (line 164):
```html
    <p>The following Kindle books on your watchlist are now on sale:</p>
```
With:
```html
    <p style="color: #555; margin-top: 5px;">The following Kindle books on your watchlist are now on sale:</p>
```

Replace the footer (lines 267-273):
```html
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">
        This is an automated notification from your Kindle Deals Monitor.
    </p>
```
With:
```html
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #e0e0e0;">
    <p style="font-size: 11px; color: #999; text-align: center;">
        Kindle Deals Monitor &middot; Automated notification
    </p>
```

**Step 2: Run tests**

Run: `pytest tests/test_email_notifier.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add src/email_notifier.py
git commit -m "style: polish email intro and footer"
```

---

### Task 5: Final verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Generate a preview email to visually verify**

Run: `python src/send_notification.py --test`

Check the received email for:
- [ ] White text on buy button
- [ ] Last known price showing
- [ ] Clean, polished layout
- [ ] Price drop badge appears correctly when there's a drop
