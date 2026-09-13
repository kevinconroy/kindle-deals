import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import sync_library  # noqa: E402


class _CountingLocator:
    def __init__(self, page):
        self._page = page

    def count(self):
        self._page.polls += 1
        return self._page.counts.pop(0) if self._page.counts else 0


class _FakePage:
    """Page whose library checkbox count follows a scripted sequence."""

    def __init__(self, counts):
        self.counts = list(counts)
        self.polls = 0
        self.slept = 0

    def locator(self, selector):
        return _CountingLocator(self)

    def wait_for_timeout(self, ms):
        self.slept += ms


def test_wait_for_library_returns_as_soon_as_books_appear():
    """The user signs in in the browser; no terminal keypress should be needed."""
    page = _FakePage([0, 0, 25])

    count = sync_library.wait_for_library(page, timeout_seconds=60, poll_interval=1)

    assert count == 25
    assert page.polls == 3


def test_wait_for_library_returns_zero_on_timeout():
    page = _FakePage([0] * 50)

    count = sync_library.wait_for_library(page, timeout_seconds=3, poll_interval=1)

    assert count == 0


def test_wait_for_library_returns_immediately_when_already_logged_in():
    page = _FakePage([12])

    assert sync_library.wait_for_library(page, timeout_seconds=60, poll_interval=1) == 12
    assert page.slept == 0  # no waiting when the library is already there


class _FakeConfig:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_resolve_headless_prefers_sync_specific_setting():
    """sync.headless lets the library sync run headed while check_deals stays
    headless — the digital console refuses headless far more often."""
    config = _FakeConfig({'sync.headless': False, 'scraping.headless': True})

    assert sync_library.resolve_headless(config) is False


def test_resolve_headless_falls_back_to_scraping_setting():
    config = _FakeConfig({'scraping.headless': True})

    assert sync_library.resolve_headless(config) is True


def test_resolve_headless_explicit_override_wins():
    config = _FakeConfig({'sync.headless': False, 'scraping.headless': False})

    assert sync_library.resolve_headless(config, headless_override=True) is True
    assert sync_library.resolve_headless(config, headless_override=False) is False


def test_resolve_headless_defaults_to_headless_when_unset():
    assert sync_library.resolve_headless(_FakeConfig({})) is True
