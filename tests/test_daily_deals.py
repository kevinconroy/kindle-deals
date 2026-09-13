import os
import sys

import pytest

# check_deals.py uses flat imports (`from config import Config`), so src must
# be importable as a top-level package directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import check_deals  # noqa: E402


class _FakeLocator:
    """Stand-in for a Playwright locator over a fixed element list."""

    def __init__(self, elements):
        self._elements = elements

    def count(self):
        return len(self._elements)

    def all(self):
        return list(self._elements)


class _FakeElement:
    def __init__(self, attrs):
        self._attrs = attrs

    def get_attribute(self, name):
        return self._attrs.get(name)


class _FakePage:
    """Fake page that serves elements per selector, recording navigation."""

    def __init__(self, selectors):
        self._selectors = selectors
        self.url = None

    def goto(self, url, **kwargs):
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        return _FakeLocator(self._selectors.get(selector, []))


def _link(href):
    return _FakeElement({'href': href})


def test_scrape_daily_deals_extracts_asins_from_product_links():
    """Current Amazon book-deals markup has no data-asin; ASINs live in /dp/ links.

    Regression for the silent Phase 2 failure: the deals page returned
    "Found 0 products" every day while the page was rendering fine.
    """
    page = _FakePage({
        'a[href*="/dp/"]': [
            _link('/dp/B000FBJHDA/ref=deals'),
            _link('https://www.amazon.com/Some-Title/dp/B000FC292K?tag=x'),
            _link('/dp/B000FCK3BE'),
        ],
    })

    asins = check_deals.scrape_daily_deals(page)

    assert sorted(asins) == ['B000FBJHDA', 'B000FC292K', 'B000FCK3BE']


def test_scrape_daily_deals_deduplicates_asins():
    page = _FakePage({
        'a[href*="/dp/"]': [
            _link('/dp/B000FBJHDA/ref=one'),
            _link('/dp/B000FBJHDA/ref=two'),
        ],
    })

    assert check_deals.scrape_daily_deals(page) == ['B000FBJHDA']


def test_scrape_daily_deals_falls_back_to_data_asin_markup():
    """Legacy grid markup must still work if Amazon serves it again."""
    page = _FakePage({
        'a[href*="/dp/"]': [],
        '[data-asin]': [
            _FakeElement({'data-asin': 'B000FBJHDA'}),
            _FakeElement({'data-asin': ''}),          # placeholder rows
            _FakeElement({'data-asin': 'tooshort'}),  # not an ASIN
        ],
    })

    assert check_deals.scrape_daily_deals(page) == ['B000FBJHDA']


def test_scrape_daily_deals_ignores_non_asin_dp_links():
    page = _FakePage({
        'a[href*="/dp/"]': [
            _link('/dp/not-an-asin'),
            _link('/gp/help/dp/'),
            _link(None),
        ],
        '[data-asin]': [],
    })

    assert check_deals.scrape_daily_deals(page) == []


def test_scrape_daily_deals_returns_empty_on_login_page():
    page = _FakePage({
        'input[name="email"]': [_FakeElement({})],
        'a[href*="/dp/"]': [_link('/dp/B000FBJHDA')],
    })

    assert check_deals.scrape_daily_deals(page) == []


def test_scrape_daily_deals_returns_empty_on_captcha():
    page = _FakePage({
        'form[action*="captcha"]': [_FakeElement({})],
        'a[href*="/dp/"]': [_link('/dp/B000FBJHDA')],
    })

    assert check_deals.scrape_daily_deals(page) == []


def test_scrape_daily_deals_warns_when_page_yields_nothing(caplog):
    """A rendering page with zero ASINs is a scraper failure, not a quiet day."""
    page = _FakePage({'a[href*="/dp/"]': [], '[data-asin]': []})

    with caplog.at_level('WARNING'):
        assert check_deals.scrape_daily_deals(page) == []

    assert any(r.levelname == 'WARNING' for r in caplog.records)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, *args):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, *a, **k):
        return _FakeCursor(self._rows)


class _FakeDB:
    """Minimal Database stand-in for the daily-deals phase."""

    def __init__(self, checked_today=()):
        self.conn = _FakeConn([(a,) for a in checked_today])
        self.deal_checks = []

    def get_bulk_last_notifications(self, asins):
        return {}

    def get_bulk_last_notification_dates(self, asins):
        return {}

    def get_bulk_previous_prices(self, asins):
        return {}

    def batch_writes(self):
        import contextlib
        return contextlib.nullcontext()

    def add_recommendation_book(self, asin, title=None, author=None):
        pass

    def add_deal_check(self, asin, was_deal, notified):
        self.deal_checks.append(asin)


class _NoMatchMatcher:
    """Matcher that loads cleanly but never matches, so the phase stops early."""

    sample_authors = ()
    sample_series = ()
    recommended_asins = ()

    def __init__(self, db):
        pass

    def is_match(self, asin, author, title):
        return False, None


@pytest.fixture
def _phase_env(monkeypatch):
    scraped = []
    monkeypatch.setattr(check_deals, 'SimilarityMatcher', _NoMatchMatcher)
    monkeypatch.setattr(check_deals, 'scrape_daily_deals', lambda *a, **k: ['B000FBJHDA'])

    def _fake_light(page, asin, **kwargs):
        scraped.append(asin)
        return {'title': 'A Title', 'author': 'An Author'}

    monkeypatch.setattr(check_deals, 'scrape_book_title_author', _fake_light)
    return scraped


def test_daily_deals_skips_asins_already_checked_today(_phase_env):
    db = _FakeDB(checked_today=['B000FBJHDA'])

    check_deals.check_daily_deals_phase(None, db, check_delay=0)

    assert _phase_env == []  # skipped, never scraped


def test_daily_deals_force_rechecks_asins_already_checked_today(_phase_env):
    """--force is documented as "check even if already checked today"; Phase 3
    writes deal_checks for every recommendation, so without this a forced re-run
    silently skips any deal that is also a tracked recommendation."""
    db = _FakeDB(checked_today=['B000FBJHDA'])

    check_deals.check_daily_deals_phase(None, db, check_delay=0, force=True)

    assert _phase_env == ['B000FBJHDA']  # re-checked despite today's record
