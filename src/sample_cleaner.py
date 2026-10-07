"""
Delete redundant Kindle samples from the Amazon digital console.

After a book is bought, Kindle usually leaves its sample in the library. This
module finds the book in the digital console and deletes only the sample, and
only after verifying the purchased copy is there too.

SAFETY: the owned copy and the sample share an ASIN, and the per-row
"Delete" button id (DELETE_TITLE_ACTION_{ASIN}) is identical on both rows, so
the per-row button is never used. Instead:
  1. Search the console and require BOTH {ASIN}:KindleEBook (owned) and
     {ASIN}:KindleEBookSample checkboxes to be present.
  2. Reload the same search in the Samples view (booksSamples) so the owned
     copy is not on the page at all, and require that no non-sample checkbox
     remains. (The "All/Samples" dropdown is not used: it navigates to the
     unfiltered booksSamples list and drops the search term.)
  3. Tick the sample checkbox and require it to be the ONLY checked box.
  4. Bulk Delete -> "Yes, delete permanently".
  5. Reload and require the sample gone and the owned copy still present.
Any deviation aborts without deleting.
"""
import logging
import re
from enum import Enum
from typing import List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

CONSOLE_BASE = "/hz/mycd/digital-console/contentlist"
ALL_VIEW = "booksAll"
SAMPLES_VIEW = "booksSamples"
CHECKBOX_SELECTOR = 'input[type="checkbox"][id*=":Kindle"]'
OWNED_SUFFIX = ':KindleEBook'
SAMPLE_SUFFIX = ':KindleEBookSample'


class Outcome(Enum):
    DELETED = 'deleted'
    ALREADY_GONE = 'already_gone'
    NO_OWNED_COPY = 'no_owned_copy'
    NOT_FOUND = 'not_found'
    NO_TITLE = 'no_title'
    DRY_RUN = 'dry_run'
    FAILED = 'failed'


class SessionExpired(Exception):
    """The digital console redirected to sign-in; stop the whole run."""


def search_term(title: str) -> str:
    """
    Shorten a title to a console search term.

    Full titles with subtitles and series tags ("Blood Meridian: Or the Evening
    Redness in the West (Vintage International)") search unreliably; the part
    before the first ':' or '(' is enough, since matches are confirmed by ASIN.
    The console also returns nothing when the term contains '&', '!', ',' or
    dashes, so punctuation other than apostrophes becomes spaces.
    """
    prefix = re.split(r'[:(]', title, maxsplit=1)[0]
    if not prefix.strip():
        prefix = title
    return ' '.join(re.sub(r"[^\w']+", ' ', prefix).split())


def console_search_url(domain: str, term: str, view: str = ALL_VIEW) -> str:
    """Return the digital-console URL that searches a library view for a term."""
    return f"https://www.{domain}{CONSOLE_BASE}/{view}/dateDsc/{quote(term, safe='')}"


def copies_present(checkbox_ids: List[str], asin: str) -> Tuple[bool, bool]:
    """Return (has_owned_copy, has_sample) for an ASIN from checkbox ids."""
    return asin + OWNED_SUFFIX in checkbox_ids, asin + SAMPLE_SUFFIX in checkbox_ids


# --- DOM helpers (patched out in tests) ------------------------------------

def open_search(page, url: str, action_delay: int) -> None:
    """Load a console search page; raise SessionExpired on a sign-in page."""
    page.goto(url)
    page.wait_for_load_state('domcontentloaded')
    try:
        page.wait_for_selector(CHECKBOX_SELECTOR, timeout=10000)
    except Exception:
        pass  # empty result set; caller decides what that means
    page.wait_for_timeout(action_delay)
    if '/ap/signin' in page.url or page.locator('input[name="password"]').count() > 0:
        raise SessionExpired(f"Redirected to sign-in: {page.url}")


def visible_checkbox_ids(page) -> List[str]:
    """Return the ids of every library item checkbox on the page."""
    return [cb.get_attribute('id') or '' for cb in page.locator(CHECKBOX_SELECTOR).all()]


def check_box(page, checkbox_id: str) -> bool:
    """
    Tick one item checkbox by exact id.

    The real <input> is aria-hidden behind a styled span with id
    "{checkbox_id}_checkmark", so click the span and read back the input.
    """
    box = page.locator(f'input[id="{checkbox_id}"]')
    checkmark = page.locator(f'span[id="{checkbox_id}_checkmark"]')
    if box.count() != 1 or checkmark.count() != 1:
        return False
    if not box.first.is_checked():
        checkmark.first.click()
        page.wait_for_timeout(500)
    return box.first.is_checked()


def checked_box_ids(page) -> List[str]:
    """Return the ids of every checked item checkbox on the page."""
    return [cb.get_attribute('id') or ''
            for cb in page.locator(CHECKBOX_SELECTOR).all() if cb.is_checked()]


def click_delete_and_confirm(page, action_delay: int) -> bool:
    """Click the bulk Delete button and confirm the dialog for a single title."""
    delete_btn = page.locator('#BULK_DELETE_TITLE_ACTION')
    if delete_btn.count() != 1 or delete_btn.get_attribute('aria-disabled') == 'true':
        logger.warning("Bulk Delete button missing or disabled")
        return False
    delete_btn.click()
    page.wait_for_timeout(action_delay)

    confirm = page.locator('#BULK_DELETE_TITLE_ACTION_CONFIRM')
    try:
        confirm.wait_for(state='visible', timeout=5000)
    except Exception:
        logger.warning("Delete confirmation dialog did not appear")
        return False

    message = page.locator('#BULK_DELETE_TITLE_DIALOG-content').inner_text()
    if not re.search(r'\b1\s+title', message):
        logger.warning(f"Unexpected delete dialog text, cancelling: {message!r}")
        page.locator('#BULK_DELETE_TITLE_ACTION_CANCEL').click()
        return False

    confirm.click()
    page.wait_for_timeout(max(action_delay, 3000))
    return True


# --- Orchestration ----------------------------------------------------------

def delete_sample(page, asin: str, title: Optional[str], domain: str,
                  dry_run: bool = False, action_delay: int = 1000,
                  verify_attempts: int = 6, verify_interval: int = 5000) -> Outcome:
    """
    Delete the sample of an owned book from the Amazon library.

    Never deletes unless the owned copy is visible alongside the sample.
    Raises SessionExpired if the console demands a sign-in.
    """
    if not title:
        logger.warning(f"{asin}: no title in database, cannot search the console")
        return Outcome.NO_TITLE

    term = search_term(title)
    url = console_search_url(domain, term)
    sample_id = asin + SAMPLE_SUFFIX

    open_search(page, url, action_delay)
    has_owned, has_sample = copies_present(visible_checkbox_ids(page), asin)
    if not has_owned and not has_sample:
        logger.warning(f"{asin}: console search for {term!r} found neither copy")
        return Outcome.NOT_FOUND
    if not has_owned:
        logger.info(f"{asin}: only the sample is in the library, leaving it alone")
        return Outcome.NO_OWNED_COPY
    if not has_sample:
        logger.info(f"{asin}: no sample in library")
        return Outcome.ALREADY_GONE
    if dry_run:
        logger.info(f"DRY RUN: would delete sample {asin} ({title})")
        return Outcome.DRY_RUN

    open_search(page, console_search_url(domain, term, SAMPLES_VIEW), action_delay)
    ids = visible_checkbox_ids(page)
    if sample_id not in ids or any(not i.endswith(SAMPLE_SUFFIX) for i in ids):
        logger.error(f"{asin}: Samples view not as expected ({ids}), aborting")
        return Outcome.FAILED

    if not check_box(page, sample_id):
        logger.error(f"{asin}: could not tick sample checkbox, aborting")
        return Outcome.FAILED
    checked = checked_box_ids(page)
    if checked != [sample_id]:
        logger.error(f"{asin}: expected only {sample_id} selected, found {checked}, aborting")
        return Outcome.FAILED

    if not click_delete_and_confirm(page, action_delay):
        return Outcome.FAILED

    # Amazon removes the item asynchronously; it can still list for a few seconds.
    for attempt in range(verify_attempts):
        if attempt:
            page.wait_for_timeout(verify_interval)
        open_search(page, url, action_delay)
        has_owned, has_sample = copies_present(visible_checkbox_ids(page), asin)
        if has_owned and not has_sample:
            logger.info(f"Deleted sample {asin} ({title})")
            return Outcome.DELETED
        if not has_owned:
            break
    logger.error(f"{asin}: after delete owned={has_owned} sample={has_sample}")
    return Outcome.FAILED
