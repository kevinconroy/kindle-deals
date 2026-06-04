import pytest
from src import purchaser


def test_parse_points_amount_with_decimals():
    text = "Use $9.99 (999 points) of Amazon Rewards Visa Card points Learn More"
    assert purchaser.parse_points_amount(text) == 9.99


def test_parse_points_amount_whole_dollars():
    text = "Use $5 (500 points) of Amazon Rewards Visa Card points"
    assert purchaser.parse_points_amount(text) == 5.0


def test_parse_points_amount_no_match_returns_none():
    assert purchaser.parse_points_amount("Add audiobook for $7.47") == 7.47
    assert purchaser.parse_points_amount("no money here") is None
    assert purchaser.parse_points_amount("") is None
    assert purchaser.parse_points_amount(None) is None


class _DummyPage:
    """Stand-in page; attempt_purchase's DOM access is monkeypatched away."""
    pass


def _patch(monkeypatch, label, box_ok, confirmed):
    monkeypatch.setattr(purchaser, 'get_points_label_text', lambda page: label)
    monkeypatch.setattr(purchaser, 'check_points_box', lambda page: box_ok)
    monkeypatch.setattr(purchaser, 'click_buy_now', lambda page: None)
    monkeypatch.setattr(purchaser, 'purchase_confirmed', lambda page: confirmed)
    monkeypatch.setattr(purchaser, '_save_screenshot', lambda *a, **k: None)


def test_attempt_purchase_no_points_checkbox(monkeypatch):
    _patch(monkeypatch, label=None, box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 3.99, action_delay=0)
    assert result['success'] is False
    assert 'no points' in result['reason'].lower()


def test_attempt_purchase_partial_coverage_skipped(monkeypatch):
    _patch(monkeypatch, label="Use $3.00 (300 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 5.00,
                                        require_full_coverage=True, action_delay=0)
    assert result['success'] is False
    assert 'cover' in result['reason'].lower()


def test_attempt_purchase_success(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99,
                                        require_full_coverage=True, action_delay=0)
    assert result['success'] is True
    assert result['points_applied'] == 4.99


def test_attempt_purchase_box_check_fails(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=False, confirmed=True)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99, action_delay=0)
    assert result['success'] is False
    assert 'box' in result['reason'].lower()


def test_attempt_purchase_not_confirmed(monkeypatch):
    _patch(monkeypatch, label="Use $4.99 (499 points) of Amazon Rewards Visa Card points",
           box_ok=True, confirmed=False)
    result = purchaser.attempt_purchase(_DummyPage(), 'B0X', 4.99, action_delay=0)
    assert result['success'] is False
    assert 'confirm' in result['reason'].lower()
