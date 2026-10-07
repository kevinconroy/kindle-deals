import pytest
from src import sample_cleaner
from src.sample_cleaner import Outcome

ASIN = 'B003XT60E0'
OWNED = f'{ASIN}:KindleEBook'
SAMPLE = f'{ASIN}:KindleEBookSample'


def test_search_term_drops_subtitle_and_series():
    assert sample_cleaner.search_term(
        'Blood Meridian: Or the Evening Redness in the West (Vintage International)'
    ) == 'Blood Meridian'
    assert sample_cleaner.search_term('Tick Town') == 'Tick Town'
    assert sample_cleaner.search_term('Unsouled (Cradle Book 1)') == 'Unsouled'


def test_search_term_strips_punctuation_the_console_cannot_search():
    # The console returns nothing for '&', '!', ',' or dashes in the search term.
    assert sample_cleaner.search_term('Shadow & Claw: The First Half') == 'Shadow Claw'
    assert sample_cleaner.search_term(
        'Of Course! The Greatest Collection Of Riddles & Brain Teasers'
    ) == 'Of Course The Greatest Collection Of Riddles Brain Teasers'
    assert sample_cleaner.search_term(
        'A Short History of Ireland, 1500\u20132000') == 'A Short History of Ireland 1500 2000'
    assert sample_cleaner.search_term("Howl's Moving Castle (Book 1)") == "Howl's Moving Castle"


def test_search_term_keeps_title_when_prefix_is_empty():
    assert sample_cleaner.search_term('(Untitled): Thing') == 'Untitled Thing'


def test_console_search_url_views():
    assert sample_cleaner.console_search_url('amazon.com', 'Tick Town') == \
        'https://www.amazon.com/hz/mycd/digital-console/contentlist/booksAll/dateDsc/Tick%20Town'
    assert sample_cleaner.console_search_url('amazon.com', 'A/B', 'booksSamples') == \
        'https://www.amazon.com/hz/mycd/digital-console/contentlist/booksSamples/dateDsc/A%2FB'


def test_copies_present_ignores_other_asins():
    ids = [OWNED, 'B0OTHER000:KindleEBookSample']
    assert sample_cleaner.copies_present(ids, ASIN) == (True, False)
    assert sample_cleaner.copies_present([OWNED, SAMPLE], ASIN) == (True, True)
    assert sample_cleaner.copies_present([SAMPLE], ASIN) == (False, True)


class _Console:
    """Scripted digital console: tracks filter state and what gets clicked."""

    def __init__(self, ids, filtered_ids=None, after_ids=None, checked=None,
                 confirm_ok=True, login=False):
        self.ids = list(ids)
        self.filtered_ids = filtered_ids if filtered_ids is not None else \
            [i for i in ids if i.endswith('Sample')]
        self.after_ids = after_ids if after_ids is not None else \
            [i for i in ids if not i.endswith('Sample')]
        self.checked = checked
        self.confirm_ok = confirm_ok
        self.login = login
        self.filtered = False
        self.deleted = False
        self.boxes_checked = []

    def install(self, monkeypatch):
        def open_search(page, url, action_delay):
            if self.login:
                raise sample_cleaner.SessionExpired('login page')
            self.filtered = '/booksSamples/' in url

        def visible_ids(page):
            if self.deleted:
                return self.after_ids
            return self.filtered_ids if self.filtered else self.ids

        def check_box(page, checkbox_id):
            self.boxes_checked.append(checkbox_id)
            return True

        def checked_ids(page):
            return self.checked if self.checked is not None else self.boxes_checked

        def delete_and_confirm(page, action_delay):
            self.deleted = self.confirm_ok
            return self.confirm_ok

        monkeypatch.setattr(sample_cleaner, 'open_search', open_search)
        monkeypatch.setattr(sample_cleaner, 'visible_checkbox_ids', visible_ids)
        monkeypatch.setattr(sample_cleaner, 'check_box', check_box)
        monkeypatch.setattr(sample_cleaner, 'checked_box_ids', checked_ids)
        monkeypatch.setattr(sample_cleaner, 'click_delete_and_confirm', delete_and_confirm)
        return self


class _Page:
    def wait_for_timeout(self, ms):
        pass


def _run(title='Blood Meridian: Or the Evening Redness', dry_run=False):
    return sample_cleaner.delete_sample(_Page(), ASIN, title, 'amazon.com',
                                        dry_run=dry_run, action_delay=0,
                                        verify_interval=0)


def test_deletes_sample_when_owned_copy_verified(monkeypatch):
    console = _Console([OWNED, SAMPLE]).install(monkeypatch)
    assert _run() == Outcome.DELETED
    assert console.boxes_checked == [SAMPLE]


def test_never_deletes_without_owned_copy(monkeypatch):
    console = _Console([SAMPLE]).install(monkeypatch)
    assert _run() == Outcome.NO_OWNED_COPY
    assert console.boxes_checked == []
    assert console.deleted is False


def test_not_found_when_search_returns_neither_copy(monkeypatch):
    console = _Console([]).install(monkeypatch)
    assert _run() == Outcome.NOT_FOUND
    assert console.boxes_checked == []


def test_reports_already_gone_when_only_owned_copy(monkeypatch):
    console = _Console([OWNED]).install(monkeypatch)
    assert _run() == Outcome.ALREADY_GONE
    assert console.boxes_checked == []


def test_dry_run_touches_nothing(monkeypatch):
    console = _Console([OWNED, SAMPLE]).install(monkeypatch)
    assert _run(dry_run=True) == Outcome.DRY_RUN
    assert console.filtered is False
    assert console.boxes_checked == []


def test_no_title_is_skipped(monkeypatch):
    console = _Console([OWNED, SAMPLE]).install(monkeypatch)
    assert _run(title=None) == Outcome.NO_TITLE
    assert console.boxes_checked == []


def test_aborts_if_samples_filter_still_shows_owned_copy(monkeypatch):
    console = _Console([OWNED, SAMPLE], filtered_ids=[OWNED, SAMPLE]).install(monkeypatch)
    assert _run() == Outcome.FAILED
    assert console.boxes_checked == []
    assert console.deleted is False


def test_aborts_if_anything_else_is_selected(monkeypatch):
    console = _Console([OWNED, SAMPLE],
                       checked=[SAMPLE, 'B0OTHER000:KindleEBookSample']).install(monkeypatch)
    assert _run() == Outcome.FAILED
    assert console.deleted is False


def test_failed_when_sample_still_present_after_confirm(monkeypatch):
    _Console([OWNED, SAMPLE], after_ids=[OWNED, SAMPLE]).install(monkeypatch)
    assert _run() == Outcome.FAILED


def test_waits_for_sample_to_disappear(monkeypatch):
    """Amazon deletes asynchronously; the first reload can still show the sample."""
    console = _Console([OWNED, SAMPLE]).install(monkeypatch)
    reloads = []

    def visible_ids(page):
        if console.deleted:
            reloads.append(1)
            return [OWNED, SAMPLE] if len(reloads) < 3 else [OWNED]
        return console.filtered_ids if console.filtered else console.ids

    monkeypatch.setattr(sample_cleaner, 'visible_checkbox_ids', visible_ids)
    assert _run() == Outcome.DELETED
    assert len(reloads) == 3


def test_failed_when_owned_copy_missing_after_delete(monkeypatch):
    _Console([OWNED, SAMPLE], after_ids=[]).install(monkeypatch)
    assert _run() == Outcome.FAILED


def test_session_expired_propagates(monkeypatch):
    _Console([OWNED, SAMPLE], login=True).install(monkeypatch)
    with pytest.raises(sample_cleaner.SessionExpired):
        _run()
