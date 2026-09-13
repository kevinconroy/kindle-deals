from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def is_deal(current_price: float, list_price: float) -> bool:
    """
    Determine if a book meets deal criteria.

    Deal criteria:
    - Price under $4.00, OR
    - At least 50% off list price
    """
    if current_price < 4.00:
        return True

    if current_price <= list_price * 0.5:
        return True

    return False


def should_notify(current_price: float, list_price: float,
                  last_notified_price: Optional[float],
                  last_notified_date: Optional[datetime] = None,
                  cooldown_days: Optional[int] = None) -> bool:
    """
    Determine if user should be notified about this deal.

    Notification rules:
    - Notify once when book first meets deal criteria
    - Notify again if price drops further
    - Notify again if the deal is still live and the last notification is
      older than cooldown_days (a book already at its floor price, e.g. $0.99,
      can never drop further and would otherwise go silent forever)

    Args:
        last_notified_date: When the book was last notified about
        cooldown_days: Re-notify about a still-live deal after this many days.
            None (the default) preserves the notify-only-on-a-lower-price rule.
    """
    if not is_deal(current_price, list_price):
        return False

    if last_notified_price is None:
        return True  # First time deal

    if current_price < last_notified_price:
        return True  # Price dropped further

    if cooldown_days and last_notified_date is not None:
        if datetime.now() - last_notified_date >= timedelta(days=cooldown_days):
            return True  # Still a deal, but the reminder has gone stale

    return False


def discount_percent(current_price: Optional[float],
                     list_price: Optional[float]) -> float:
    """
    Percent off list price, 0.0 when it can't be determined.
    """
    if not current_price or not list_price or list_price <= 0:
        return 0.0
    return max(0.0, (list_price - current_price) / list_price * 100.0)


def rank_deals_for_email(deals: List[Dict[str, Any]],
                         limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Order deals best-discount-first and cap how many go in one email.

    Enabling the cooldown surfaces a large backlog of long-suppressed deals at
    once; capping spreads it over subsequent runs instead of sending one huge
    email. Deals left out stay unnotified, so they are picked up next run.

    Args:
        limit: Maximum deals to return. None or 0 returns all of them.
    """
    ranked = sorted(
        deals,
        key=lambda d: (
            -discount_percent(d.get('current_price'), d.get('list_price')),
            d.get('current_price') or 0.0,
        ),
    )

    if not limit:
        return ranked

    return ranked[:limit]
