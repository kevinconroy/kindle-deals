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
