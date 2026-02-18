"""Similarity matching for daily deals based on user's sample library."""

import re
from typing import Tuple, Set, Dict
from database import Database


class SimilarityMatcher:
    """Matches deal books against user's reading interests."""

    def __init__(self, db: Database):
        """
        Initialize matcher with cached data from database.

        Args:
            db: Database instance
        """
        self.db = db

        # Cache sets for fast O(1) lookups
        self.sample_authors: Set[str] = set()
        self.sample_series: Set[str] = set()
        self.recommended_asins: Dict[str, str] = {}

        self._load_cache()

    def _load_cache(self) -> None:
        """Load matching data from database into memory."""
        # Get all active sample books
        books = self.db.get_sample_books()

        for book in books:
            # Store author (normalized)
            author = book.get('author')
            if author:
                self.sample_authors.add(author.lower().strip())

            # Extract series from title
            title = book.get('title')
            if title:
                series = self._extract_series(title)
                if series:
                    self.sample_series.add(series.lower().strip())

        # Get all recommended ASINs
        self.recommended_asins = self.db.get_all_recommended_asins()

    def _extract_series(self, title: str) -> str:
        """
        Extract series name from book title.

        Common patterns:
        - "Book Title (Series Name, Book 1)"
        - "Book Title (Series Name #1)"
        - "Series Name: Book Title"

        Args:
            title: Book title

        Returns:
            Series name or empty string if not found
        """
        # Pattern: "Title (Series, Book N)" or "Title (Series #N)"
        match = re.search(r'\(([^,#)]+)[,#]', title)
        if match:
            return match.group(1).strip()

        # Pattern: "Series: Title"
        if ':' in title:
            parts = title.split(':', 1)
            # Only consider it a series if first part is reasonably short
            if len(parts[0]) < 50:
                return parts[0].strip()

        return ''

    def is_match(self, asin: str, author: str, title: str) -> Tuple[bool, str]:
        """
        Check if deal book matches user's interests.

        Checks three signals in priority order:
        1. Same author as a sample book
        2. Same series as a sample book
        3. Recommended from a sample book

        Args:
            asin: Deal book ASIN
            author: Deal book author
            title: Deal book title

        Returns:
            (is_match: bool, reason: str)

        Examples:
            (True, "Same author: Brandon Sanderson")
            (True, "Same series: Mistborn")
            (True, "Recommended from: The Way of Kings")
            (False, "")
        """
        # Check 1: Author match
        if author:
            normalized_author = author.lower().strip()
            if normalized_author in self.sample_authors:
                return (True, f"Same author: {author}")

        # Check 2: Series match
        series = self._extract_series(title)
        if series:
            normalized_series = series.lower().strip()
            if normalized_series in self.sample_series:
                return (True, f"Same series: {series}")

        # Check 3: Recommendation match
        if asin in self.recommended_asins:
            source_title = self.recommended_asins[asin]
            return (True, f"Recommended from: {source_title}")

        return (False, "")
