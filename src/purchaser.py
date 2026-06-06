"""Auto-purchase a Kindle sample with 1-Click using Amazon Rewards points.

The orchestration in `attempt_purchase` is unit-tested by monkeypatching the
thin DOM helpers below. The actual DOM helpers are validated live.
"""
import logging
import os
import re
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

POINTS_CHECKBOX = '#balance-checkbox-0'
BUY_NOW_BUTTON = '#one-click-button'
POINTS_LABEL_PHRASE = 'Amazon Rewards Visa Card points'

# Signals that an order succeeded / the book is now owned
CONFIRM_SELECTORS = [
    'button:has-text("Read Now")', 'a:has-text("Read Now")',
    '#kindle-reader-button', 'a[href*="/read/"]',
    'input[value*="Read Now"]', '#kop-button-ingress',
]


def parse_points_amount(label_text: Optional[str]) -> Optional[float]:
    """Extract the dollar amount from a points checkbox label.

    Example: "Use $9.99 (999 points) of Amazon Rewards Visa Card points" -> 9.99
    Returns None if no amount is found.
    """
    if not label_text:
        return None
    match = re.search(r'\$(\d+(?:\.\d{2})?)', label_text)
    if not match:
        return None
    return float(match.group(1))


def get_points_label_text(page) -> Optional[str]:
    """Read the full points-checkbox label text, e.g.
    'Use $9.99 (999 points) of Amazon Rewards Visa Card points'.
    Returns None if the points checkbox is not present."""
    try:
        cb = page.locator(POINTS_CHECKBOX)
        if cb.count() == 0:
            return None
        container = cb.locator(
            f"xpath=ancestor::*[contains(normalize-space(.), '{POINTS_LABEL_PHRASE}')][1]"
        )
        if container.count() == 0:
            return None
        return container.first.inner_text().strip()
    except Exception as e:
        logger.debug(f"get_points_label_text failed: {e}")
        return None


def check_points_box(page) -> bool:
    """Check ONLY the points checkbox (never the adjacent audiobook checkbox).
    Returns True if it ends up checked."""
    try:
        cb = page.locator(POINTS_CHECKBOX).first
        if cb.count() == 0:
            return False
        if not cb.is_checked():
            cb.check()
        return cb.is_checked()
    except Exception as e:
        logger.debug(f"check_points_box failed: {e}")
        return False


def points_applied_to_order(page) -> bool:
    """Authoritative check that the order will actually be paid with points.

    Ticking the points checkbox does NOT submit the checkbox itself (it has no
    name). Instead a JS handler injects `payment.applicableBalances[0]` (value
    "ExternalPoints") into the 1-Click form ~0.5s later. That hidden field IS
    the order payload, so it is the only reliable signal that points will be
    used. Returns False if the field is absent (order would charge real money)
    or if the form/button is missing.
    """
    try:
        btn = page.locator(BUY_NOW_BUTTON).first
        if btn.count() == 0:
            return False
        value = btn.evaluate(
            """el => {
                const f = el.closest('form');
                if (!f) return null;
                const i = f.querySelector('input[name="payment.applicableBalances[0]"]');
                return i ? i.value : null;
            }"""
        )
        return value == 'ExternalPoints'
    except Exception as e:
        logger.debug(f"points_applied_to_order failed: {e}")
        return False


def click_buy_now(page) -> None:
    """Click the 1-Click buy button. Places the order instantly."""
    page.locator(BUY_NOW_BUTTON).first.click()


def purchase_confirmed(page) -> bool:
    """After clicking buy, confirm the order placed by detecting a
    'Read Now' / reader signal or order-confirmation text."""
    try:
        page.wait_for_timeout(3000)
    except Exception:
        pass
    for sel in CONFIRM_SELECTORS:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    try:
        body = page.locator('body').inner_text().lower()
        if 'thank you' in body or 'order has been placed' in body or 'you purchased' in body:
            return True
    except Exception:
        pass
    return False


def _save_screenshot(page, screenshot_dir: Optional[str], name: str) -> None:
    if not screenshot_dir:
        return
    try:
        path = os.path.join(screenshot_dir, f"purchase-{name}.png")
        page.screenshot(path=path)
        logger.debug(f"Saved screenshot {path}")
    except Exception as e:
        logger.debug(f"Screenshot failed: {e}")


def attempt_purchase(page, asin: str, current_price: float,
                     require_full_coverage: bool = True,
                     screenshot_dir: Optional[str] = None,
                     action_delay: float = 0.5,
                     points_confirm_timeout: float = 6.0) -> Dict[str, Any]:
    """Attempt to buy `asin` with 1-Click, applying Rewards points.

    SAFETY: never clicks buy unless points are positively confirmed to be
    attached to the order (`points_applied_to_order`). If that confirmation
    cannot be obtained, the purchase is aborted so we never spend real cash.

    Returns {"success": bool, "points_applied": float|None, "reason": str}.
    Only returns success after a confirmed order.
    """
    label = get_points_label_text(page)
    if not label:
        return {"success": False, "points_applied": None, "reason": "no points checkbox"}

    amount = parse_points_amount(label)
    if amount is None:
        return {"success": False, "points_applied": None,
                "reason": "could not parse points amount"}

    if require_full_coverage and amount + 1e-9 < current_price:
        return {"success": False, "points_applied": None,
                "reason": f"points ${amount:.2f} do not cover ${current_price:.2f}"}

    _save_screenshot(page, screenshot_dir, f"{asin}-before")

    if not check_points_box(page):
        return {"success": False, "points_applied": None,
                "reason": "could not check points box"}

    # Wait for the points-payment field to attach to the order. The handler that
    # injects payment.applicableBalances[0]=ExternalPoints lands ~0.5s after the
    # tick; clicking buy before then charges real money (the original bug).
    applied = points_applied_to_order(page)
    deadline = time.time() + points_confirm_timeout
    while not applied and time.time() < deadline:
        time.sleep(0.25)
        applied = points_applied_to_order(page)

    if not applied:
        return {"success": False, "points_applied": None,
                "reason": "points not applied to order — aborting to avoid spending cash"}

    # Defense in depth: re-verify on a fresh read immediately before the
    # irreversible 1-Click. If the points field vanished, do not buy.
    if not points_applied_to_order(page):
        return {"success": False, "points_applied": None,
                "reason": "points application lost before checkout — aborting"}

    logger.info(f"Points confirmed on order; placing 1-Click order for {asin} (points ${amount:.2f})")
    click_buy_now(page)
    time.sleep(action_delay)

    confirmed = purchase_confirmed(page)
    _save_screenshot(page, screenshot_dir, f"{asin}-after")

    if not confirmed:
        return {"success": False, "points_applied": None,
                "reason": "no purchase confirmation"}

    return {"success": True, "points_applied": amount, "reason": "purchased"}
