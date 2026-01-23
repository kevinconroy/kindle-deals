from playwright.sync_api import sync_playwright, Page, Browser
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AmazonScraper:
    def __init__(self, session_path: str, headless: bool = True,
                 page_timeout: int = 30000):
        self.session_path = session_path
        self.headless = headless
        self.page_timeout = page_timeout
        self.playwright = None
        self.browser = None
        self.context = None

    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)

        # Use persistent context to save login session
        self.context = self.browser.new_context(
            storage_state=self.session_path if self._session_exists() else None
        )
        self.context.set_default_timeout(self.page_timeout)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            # Save session state
            self.context.storage_state(path=self.session_path)
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _session_exists(self) -> bool:
        import os
        return os.path.exists(self.session_path)

    def new_page(self) -> Page:
        return self.context.new_page()

    def retry_with_backoff(self, func, max_attempts: int = 3,
                          initial_delay: float = 1.0):
        """Retry function with exponential backoff"""
        delay = initial_delay
        last_exception = None

        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2

        raise last_exception


def extract_price(price_text: Optional[str]) -> Optional[float]:
    """Extract price from text like '$3.99' or '3.99'"""
    if not price_text:
        return None

    # Remove currency symbols and whitespace
    cleaned = price_text.replace('$', '').replace(',', '').strip()

    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Could not parse price: {price_text}")
        return None


def calculate_savings_percent(current_price: float, list_price: float) -> int:
    """Calculate savings percentage"""
    if list_price == 0:
        return 0

    savings = ((list_price - current_price) / list_price) * 100
    return int(round(savings))
