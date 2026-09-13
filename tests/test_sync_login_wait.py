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
