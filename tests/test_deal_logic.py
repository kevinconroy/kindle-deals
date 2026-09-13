import pytest
from src.deal_logic import is_deal, should_notify


def test_is_deal_under_four_dollars():
    assert is_deal(current_price=3.99, list_price=9.99) is True
    assert is_deal(current_price=3.50, list_price=15.00) is True


def test_is_deal_fifty_percent_off():
    assert is_deal(current_price=5.00, list_price=10.00) is True
    assert is_deal(current_price=4.99, list_price=10.00) is True


def test_not_a_deal():
    assert is_deal(current_price=5.00, list_price=9.00) is False
    assert is_deal(current_price=6.00, list_price=10.00) is False


def test_should_notify_first_time_deal():
    # First time deal - should notify
    assert should_notify(
        current_price=3.99,
        list_price=9.99,
        last_notified_price=None
    ) is True


def test_should_notify_price_drop():
    # Price dropped from $3.99 to $2.99 - should notify
    assert should_notify(
        current_price=2.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is True


def test_should_not_notify_same_price():
    # Same price as last notification - should not notify
    assert should_notify(
        current_price=3.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is False


def test_should_not_notify_price_increase():
    # Price increased - should not notify
    assert should_notify(
        current_price=4.99,
        list_price=9.99,
        last_notified_price=3.99
    ) is False


def test_should_not_notify_not_a_deal():
    # Not a deal - should not notify
    assert should_notify(
        current_price=7.00,
        list_price=9.99,
        last_notified_price=None
    ) is False


# --- 30-day re-notification cooldown -------------------------------------

from datetime import datetime, timedelta  # noqa: E402

from src.deal_logic import rank_deals_for_email  # noqa: E402


def test_cooldown_renotifies_a_still_live_deal_after_the_window():
    """A $0.99 book can never drop further, so without a cooldown it goes
    silent forever. After 30 days it should surface again."""
    assert should_notify(
        current_price=0.99,
        list_price=21.99,
        last_notified_price=0.99,
        last_notified_date=datetime.now() - timedelta(days=31),
        cooldown_days=30,
    ) is True


def test_cooldown_does_not_renotify_inside_the_window():
    assert should_notify(
        current_price=0.99,
        list_price=21.99,
        last_notified_price=0.99,
        last_notified_date=datetime.now() - timedelta(days=10),
        cooldown_days=30,
    ) is False


def test_cooldown_never_resurrects_a_non_deal():
    assert should_notify(
        current_price=25.00,
        list_price=30.00,
        last_notified_price=1.99,
        last_notified_date=datetime.now() - timedelta(days=200),
        cooldown_days=30,
    ) is False


def test_cooldown_disabled_preserves_existing_behavior():
    """Without cooldown_days the old monotonic rule must hold exactly."""
    old = datetime.now() - timedelta(days=365)
    assert should_notify(0.99, 21.99, 0.99, last_notified_date=old) is False
    assert should_notify(0.99, 21.99, None) is True
    assert should_notify(0.99, 21.99, 1.99) is True


def test_price_drop_still_notifies_inside_the_cooldown_window():
    assert should_notify(
        current_price=0.99,
        list_price=21.99,
        last_notified_price=2.99,
        last_notified_date=datetime.now() - timedelta(days=1),
        cooldown_days=30,
    ) is True


# --- staggering the backlog ----------------------------------------------

def test_rank_deals_for_email_caps_and_orders_by_discount():
    deals = [
        {'asin': 'A', 'current_price': 5.00, 'list_price': 10.00},   # 50%
        {'asin': 'B', 'current_price': 0.99, 'list_price': 21.99},   # ~95%
        {'asin': 'C', 'current_price': 2.99, 'list_price': 20.00},   # ~85%
    ]

    ranked = rank_deals_for_email(deals, limit=2)

    assert [d['asin'] for d in ranked] == ['B', 'C']


def test_rank_deals_for_email_handles_missing_list_price():
    deals = [
        {'asin': 'A', 'current_price': 3.00, 'list_price': None},
        {'asin': 'B', 'current_price': 1.00, 'list_price': 20.00},
    ]

    ranked = rank_deals_for_email(deals, limit=5)

    assert [d['asin'] for d in ranked] == ['B', 'A']  # unknown discount ranks last
    assert len(ranked) == 2


def test_rank_deals_for_email_no_limit_returns_all():
    deals = [{'asin': str(i), 'current_price': 1.0, 'list_price': 10.0} for i in range(50)]
    assert len(rank_deals_for_email(deals, limit=None)) == 50
    assert len(rank_deals_for_email(deals, limit=0)) == 50
