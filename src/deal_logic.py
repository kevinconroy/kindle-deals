from typing import Optional


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
                 last_notified_price: Optional[float]) -> bool:
    """
    Determine if user should be notified about this deal.

    Notification rules:
    - Notify once when book first meets deal criteria
    - Notify again only if price drops further
    """
    if not is_deal(current_price, list_price):
        return False

    if last_notified_price is None:
        return True  # First time deal

    if current_price < last_notified_price:
        return True  # Price dropped further

    return False
