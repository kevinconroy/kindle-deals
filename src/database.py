import mysql.connector
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, host: str, user: str, password: str, database: str):
        """
        Initialize database connection.

        Args:
            host: MySQL server host
            user: MySQL username
            password: MySQL password
            database: Database name
        """
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self._batch_mode = False

        # Create database if it doesn't exist
        self._create_database_if_not_exists()

        # Connect to the database
        self.conn = mysql.connector.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            database=self.database
        )

        # Create tables
        self._create_tables()

    def _create_database_if_not_exists(self):
        """Create the database if it doesn't exist."""
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}`")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _create_tables(self):
        """Create all required tables if they don't exist."""
        cursor = self.conn.cursor()
        try:
            # Books table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    asin VARCHAR(20) PRIMARY KEY,
                    title VARCHAR(500),
                    author VARCHAR(255),
                    cover_url VARCHAR(1000),
                    date_added DATETIME NOT NULL,
                    is_sample TINYINT(1) DEFAULT 1,
                    is_deleted TINYINT(1) DEFAULT 0,
                    is_recommendation TINYINT(1) DEFAULT 0,
                    has_owned_copy TINYINT(1) DEFAULT 0
                )
            """)

            # Migrate existing table to allow NULL title (for existing databases)
            try:
                cursor.execute("""
                    ALTER TABLE books MODIFY title VARCHAR(500) NULL
                """)
            except Exception:
                # Ignore if already nullable or other issues
                pass

            # Migrate is_active -> is_sample + is_deleted (for existing databases)
            try:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'books' AND COLUMN_NAME = 'is_active'
                """, (self.database,))
                if cursor.fetchone():
                    # Old schema detected: add new columns and migrate data
                    try:
                        cursor.execute("ALTER TABLE books ADD COLUMN is_sample TINYINT(1) DEFAULT 1")
                    except Exception:
                        pass  # Column may already exist
                    try:
                        cursor.execute("ALTER TABLE books ADD COLUMN is_deleted TINYINT(1) DEFAULT 0")
                    except Exception:
                        pass  # Column may already exist
                    # Migrate: is_active=1 -> is_sample=1, is_deleted=0
                    #          is_active=0 -> is_sample=1, is_deleted=1
                    cursor.execute("UPDATE books SET is_sample = 1, is_deleted = CASE WHEN is_active = 0 THEN 1 ELSE 0 END")
                    cursor.execute("ALTER TABLE books DROP COLUMN is_active")
                    self.conn.commit()
            except Exception:
                pass

            # Migrate: add is_recommendation column (for existing databases)
            try:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'books' AND COLUMN_NAME = 'is_recommendation'
                """, (self.database,))
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE books ADD COLUMN is_recommendation TINYINT(1) DEFAULT 0")
                    self.conn.commit()
            except Exception:
                pass

            # Migrate: add has_owned_copy column (for existing databases)
            try:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'books' AND COLUMN_NAME = 'has_owned_copy'
                """, (self.database,))
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE books ADD COLUMN has_owned_copy TINYINT(1) DEFAULT 0")
                    self.conn.commit()
            except Exception:
                pass

            # Price history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    price DECIMAL(10,2),
                    list_price DECIMAL(10,2),
                    check_date DATETIME NOT NULL,
                    FOREIGN KEY (asin) REFERENCES books(asin),
                    INDEX idx_price_history_asin_date (asin, check_date),
                    INDEX idx_price_history_asin_id (asin, id)
                )
            """)

            # Notifications table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    notified_price DECIMAL(10,2) NOT NULL,
                    notified_date DATETIME NOT NULL,
                    FOREIGN KEY (asin) REFERENCES books(asin)
                )
            """)

            # Recommendations table - stores "also bought" data
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    source_asin VARCHAR(20) NOT NULL,
                    recommended_asin VARCHAR(20) NOT NULL,
                    created_date DATETIME NOT NULL,
                    FOREIGN KEY (source_asin) REFERENCES books(asin),
                    INDEX idx_recommended_asin (recommended_asin),
                    UNIQUE KEY unique_recommendation (source_asin, recommended_asin)
                )
            """)

            # Deal checks table - tracks processed daily deals
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deal_checks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    check_date DATE NOT NULL,
                    was_deal TINYINT(1) NOT NULL,
                    notified TINYINT(1) NOT NULL,
                    UNIQUE KEY unique_daily_check (asin, check_date)
                )
            """)

            # Purchases table - records auto-purchased books for idempotency/audit
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchases (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    price DECIMAL(10,2) NOT NULL,
                    points_applied DECIMAL(10,2),
                    purchased_date DATETIME NOT NULL,
                    UNIQUE KEY unique_purchase (asin),
                    FOREIGN KEY (asin) REFERENCES books(asin)
                )
            """)

            # Migrate: add performance indexes (for existing databases)
            try:
                cursor.execute("""
                    SELECT INDEX_NAME FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'price_history'
                    AND INDEX_NAME = 'idx_price_history_asin_date'
                """, (self.database,))
                rows = cursor.fetchall()
                if not rows:
                    cursor.execute("ALTER TABLE price_history ADD INDEX idx_price_history_asin_date (asin, check_date)")
                    cursor.execute("ALTER TABLE price_history ADD INDEX idx_price_history_asin_id (asin, id)")
                    self.conn.commit()
            except Exception:
                pass

            self.conn.commit()
        finally:
            cursor.close()

    def add_book(self, asin: str, title: str = None, author: str = None,
                 cover_url: str = None, is_sample: bool = True) -> bool:
        """
        Add a new book to the database.

        Args:
            asin: Amazon Standard Identification Number
            title: Book title (optional, will be NULL if not provided)
            author: Book author (optional)
            cover_url: URL to book cover image (optional)
            is_sample: Whether this is a sample (True) or owned book (False)

        Returns:
            True if book was newly added, False if already existed
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT IGNORE INTO books (asin, title, author, cover_url, date_added, is_sample, is_deleted)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
            """, (asin, title, author, cover_url, datetime.now(), 1 if is_sample else 0))
            self.conn.commit()

            # Log how many rows were affected (0 if already exists due to INSERT IGNORE)
            if cursor.rowcount == 0:
                return False  # Already existed
            return True  # Newly added
        finally:
            cursor.close()

    def get_book(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get a book by ASIN.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with book data or None if not found
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM books WHERE asin = %s", (asin,))
            result = cursor.fetchone()
            return result
        finally:
            cursor.close()

    def update_book_metadata(self, asin: str, title: str, author: str = None,
                            cover_url: str = None) -> None:
        """
        Update book metadata (title, author, cover_url).

        Args:
            asin: Amazon Standard Identification Number
            title: Book title
            author: Book author (optional)
            cover_url: URL to book cover image (optional)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE books
                SET title = %s, author = %s, cover_url = %s
                WHERE asin = %s
            """, (title, author, cover_url, asin))
            if not self._batch_mode:
                self.conn.commit()
        finally:
            cursor.close()

    def mark_book_deleted(self, asin: str) -> None:
        """
        Mark a book as deleted (no longer tracking).

        Args:
            asin: Amazon Standard Identification Number
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE books
                SET is_deleted = 1
                WHERE asin = %s
            """, (asin,))
            self.conn.commit()
        finally:
            cursor.close()

    def undelete_book(self, asin: str) -> None:
        """Restore a deleted book."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE books
                SET is_deleted = 0
                WHERE asin = %s
            """, (asin,))
            self.conn.commit()
        finally:
            cursor.close()

    def update_book_sample_status(self, asin: str, is_sample: bool) -> None:
        """Update whether a book is a sample or owned."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE books SET is_sample = %s WHERE asin = %s
            """, (1 if is_sample else 0, asin))
            self.conn.commit()
        finally:
            cursor.close()

    def add_price_history(self, asin: str, price: float,
                         list_price: float = None) -> None:
        """
        Add a price history entry for a book.

        Args:
            asin: Amazon Standard Identification Number
            price: Current price
            list_price: Original list price (optional)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO price_history (asin, price, list_price, check_date)
                VALUES (%s, %s, %s, %s)
            """, (asin, price, list_price, datetime.now()))
            if not self._batch_mode:
                self.conn.commit()
        finally:
            cursor.close()

    def get_latest_price(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent price check for a book.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with price data or None if no history exists
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT * FROM price_history
                WHERE asin = %s
                ORDER BY id DESC
                LIMIT 1
            """, (asin,))
            result = cursor.fetchone()
            return result
        finally:
            cursor.close()

    def get_previous_price(self, asin: str) -> Optional[float]:
        """
        Get the most recent price for a book from a prior check.

        Called before saving today's price, so the most recent entry
        in price_history is from the previous check.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Previous price as float or None if no previous price exists
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT price FROM price_history
                WHERE asin = %s
                ORDER BY id DESC
                LIMIT 1
            """, (asin,))
            result = cursor.fetchone()
            return float(result['price']) if result and result['price'] is not None else None
        finally:
            cursor.close()

    def was_checked_today(self, asin: str, deal_day: datetime) -> bool:
        """
        Check if a book was already checked on the current deal day.

        Args:
            asin: Amazon Standard Identification Number
            deal_day: The current deal day (midnight)

        Returns:
            True if already checked today, False otherwise
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) as count FROM price_history
                WHERE asin = %s AND check_date >= %s
            """, (asin, deal_day))
            result = cursor.fetchone()
            return result[0] > 0
        finally:
            cursor.close()

    def add_notification(self, asin: str, notified_price: float) -> None:
        """
        Add a notification record for a book.

        Args:
            asin: Amazon Standard Identification Number
            notified_price: Price at which notification was sent
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO notifications (asin, notified_price, notified_date)
                VALUES (%s, %s, %s)
            """, (asin, notified_price, datetime.now()))
            if not self._batch_mode:
                self.conn.commit()
        finally:
            cursor.close()

    def get_last_notification(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent notification for a book.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with notification data or None if no notifications exist
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT * FROM notifications
                WHERE asin = %s
                ORDER BY id DESC
                LIMIT 1
            """, (asin,))
            result = cursor.fetchone()
            return result
        finally:
            cursor.close()

    def add_purchase(self, asin: str, price: float,
                     points_applied: float = None) -> None:
        """
        Record an auto-purchase. Idempotent: a second call for the same ASIN
        is ignored (UNIQUE constraint on asin).

        Args:
            asin: Amazon Standard Identification Number
            price: Price paid
            points_applied: Dollar value of Rewards points applied (or None)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT IGNORE INTO purchases (asin, price, points_applied, purchased_date)
                VALUES (%s, %s, %s, %s)
            """, (asin, price, points_applied, datetime.now()))
            self.conn.commit()
        finally:
            cursor.close()

    def is_purchased(self, asin: str) -> bool:
        """Return True if this ASIN has already been auto-purchased."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT 1 FROM purchases WHERE asin = %s LIMIT 1", (asin,))
            return cursor.fetchone() is not None
        finally:
            cursor.close()

    def get_sample_books(self) -> List[Dict[str, Any]]:
        """
        Get all sample books that are not deleted and don't have an owned copy.

        Books with has_owned_copy=1 are excluded — the user already owns them,
        so there's no need to track deals on the sample.

        Returns:
            List of dictionaries with book data
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT * FROM books
                WHERE is_sample = 1 AND is_deleted = 0 AND has_owned_copy = 0
            """)
            results = cursor.fetchall()
            return results
        finally:
            cursor.close()

    def set_has_owned_copy(self, asin: str, value: bool) -> None:
        """
        Mark or unmark a sample book as also having an owned copy.

        When True, the book is excluded from deal checking since the user
        already owns the full book. The sample can be deleted from the library.

        Args:
            asin: Amazon Standard Identification Number
            value: True if an owned copy exists alongside the sample
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE books SET has_owned_copy = %s WHERE asin = %s
            """, (1 if value else 0, asin))
            self.conn.commit()
        finally:
            cursor.close()

    def get_samples_with_owned_copies(self) -> List[Dict[str, Any]]:
        """
        Get all sample books that also have an owned copy.

        These are candidates for sample deletion — the user owns the full book
        and the sample is redundant.

        Returns:
            List of dictionaries with book data (asin, title, author, etc.)
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT * FROM books
                WHERE is_sample = 1 AND is_deleted = 0 AND has_owned_copy = 1
                ORDER BY title
            """)
            results = cursor.fetchall()
            return results
        finally:
            cursor.close()

    def add_recommendation(self, source_asin: str, recommended_asin: str) -> None:
        """
        Add a recommendation (also bought) for a book.

        Args:
            source_asin: The book that has the recommendation
            recommended_asin: The recommended book ASIN
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO recommendations (source_asin, recommended_asin, created_date)
                VALUES (%s, %s, %s)
            """, (source_asin, recommended_asin, datetime.now()))
            self.conn.commit()
        except mysql.connector.IntegrityError:
            # Duplicate recommendation - already exists, ignore
            self.conn.rollback()
            pass
        finally:
            cursor.close()

    def get_recommendations(self, source_asin: str) -> List[str]:
        """
        Get all recommended ASINs for a source book.

        Args:
            source_asin: The book to get recommendations for

        Returns:
            List of recommended ASINs
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT recommended_asin FROM recommendations
                WHERE source_asin = %s
            """, (source_asin,))
            results = cursor.fetchall()
            return [row[0] for row in results]
        finally:
            cursor.close()

    def has_recommendations(self, source_asin: str) -> bool:
        """
        Check if we've already scraped recommendations for this book.

        Args:
            source_asin: The book to check

        Returns:
            True if recommendations exist, False otherwise
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM recommendations
                WHERE source_asin = %s
            """, (source_asin,))
            count = cursor.fetchone()[0]
            return count > 0
        finally:
            cursor.close()

    def get_all_recommended_asins(self) -> Dict[str, str]:
        """
        Get all recommended ASINs with their source book titles.

        Returns:
            Dict mapping recommended_asin -> source_book_title
            (titles are 'Unknown' if not yet fetched from API)
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT r.recommended_asin, b.title
                FROM recommendations r
                JOIN books b ON r.source_asin = b.asin
                WHERE b.is_sample = 1 AND b.is_deleted = 0
            """)
            results = cursor.fetchall()
            return {row['recommended_asin']: row['title'] or 'Unknown' for row in results}
        finally:
            cursor.close()

    def add_deal_check(self, asin: str, was_deal: bool, notified: bool) -> None:
        """
        Record that we checked a daily deal.

        Args:
            asin: Book ASIN
            was_deal: Whether it met deal criteria
            notified: Whether we sent notification

        Note:
            Uses INSERT...IGNORE pattern - if already checked today, silently ignores.
            This prevents duplicate processing of the same deal on the same day.
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT IGNORE INTO deal_checks (asin, check_date, was_deal, notified)
                VALUES (%s, CURDATE(), %s, %s)
            """, (asin, 1 if was_deal else 0, 1 if notified else 0))
            if not self._batch_mode:
                self.conn.commit()
        finally:
            cursor.close()

    def was_deal_checked_today(self, asin: str) -> bool:
        """
        Check if we already processed this deal today.

        Args:
            asin: Book ASIN

        Returns:
            True if already checked today, False otherwise
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM deal_checks
                WHERE asin = %s AND check_date = CURDATE()
            """, (asin,))
            count = cursor.fetchone()[0]
            return count > 0
        finally:
            cursor.close()

    def get_unchecked_recommendation_asins(self) -> List[str]:
        """
        Get all recommended ASINs that haven't been checked today.

        Returns ASINs from recommendations table where the source book
        is an active sample, excluding any already in deal_checks for today.

        Returns:
            List of recommended ASIN strings
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT DISTINCT r.recommended_asin
                FROM recommendations r
                JOIN books b ON r.source_asin = b.asin
                WHERE b.is_sample = 1 AND b.is_deleted = 0
                AND r.recommended_asin NOT IN (
                    SELECT asin FROM deal_checks WHERE check_date = CURDATE()
                )
            """)
            results = cursor.fetchall()
            return [row[0] for row in results]
        finally:
            cursor.close()

    def add_recommendation_book(self, asin: str, title: str = None,
                                author: str = None, cover_url: str = None) -> None:
        """
        Add or update a book discovered via recommendations.

        If the book doesn't exist, inserts with is_recommendation=1, is_sample=0.
        If the book already exists (e.g., as a sample), only updates metadata
        (title, author, cover_url) without changing is_sample or is_recommendation.

        Args:
            asin: Amazon Standard Identification Number
            title: Book title (optional)
            author: Book author (optional)
            cover_url: URL to book cover image (optional)
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO books (asin, title, author, cover_url, date_added, is_sample, is_deleted, is_recommendation)
                VALUES (%s, %s, %s, %s, %s, 0, 0, 1)
                ON DUPLICATE KEY UPDATE
                    title = COALESCE(%s, title),
                    author = COALESCE(%s, author),
                    cover_url = COALESCE(%s, cover_url)
            """, (asin, title, author, cover_url, datetime.now(), title, author, cover_url))
            if not self._batch_mode:
                self.conn.commit()
        finally:
            cursor.close()

    def get_recommendation_source(self, asin: str) -> Optional[str]:
        """
        Get the source book title for a recommended ASIN.

        Args:
            asin: The recommended book's ASIN

        Returns:
            Source book title, or None if not found
        """
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT b.title
                FROM recommendations r
                JOIN books b ON r.source_asin = b.asin
                WHERE r.recommended_asin = %s
                AND b.is_sample = 1 AND b.is_deleted = 0
                LIMIT 1
            """, (asin,))
            result = cursor.fetchone()
            return result['title'] if result else None
        finally:
            cursor.close()

    def get_checked_today_asins(self, deal_day) -> set:
        """Bulk-fetch all ASINs that already have a price_history entry since deal_day."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT DISTINCT asin FROM price_history WHERE check_date >= %s
            """, (deal_day,))
            return {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def get_bulk_previous_prices(self, asins: list) -> dict:
        """Fetch the most recent price for each ASIN in one query. Returns dict asin->float."""
        if not asins:
            return {}
        placeholders = ','.join(['%s'] * len(asins))
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute(f"""
                SELECT ph.asin, ph.price
                FROM price_history ph
                INNER JOIN (
                    SELECT asin, MAX(id) AS max_id
                    FROM price_history
                    WHERE asin IN ({placeholders})
                    GROUP BY asin
                ) latest ON ph.asin = latest.asin AND ph.id = latest.max_id
            """, asins)
            return {
                row['asin']: float(row['price'])
                for row in cursor.fetchall()
                if row['price'] is not None
            }
        finally:
            cursor.close()

    def get_bulk_last_notifications(self, asins: list) -> dict:
        """Fetch the most recent notified_price for each ASIN in one query. Returns dict asin->float."""
        if not asins:
            return {}
        placeholders = ','.join(['%s'] * len(asins))
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute(f"""
                SELECT n.asin, n.notified_price
                FROM notifications n
                INNER JOIN (
                    SELECT asin, MAX(id) AS max_id
                    FROM notifications
                    WHERE asin IN ({placeholders})
                    GROUP BY asin
                ) latest ON n.asin = latest.asin AND n.id = latest.max_id
            """, asins)
            return {
                row['asin']: float(row['notified_price'])
                for row in cursor.fetchall()
                if row['notified_price'] is not None
            }
        finally:
            cursor.close()

    def get_existing_asins(self, asins: list) -> set:
        """Bulk check which ASINs already exist in books table. Replaces per-book get_book() calls."""
        if not asins:
            return set()
        placeholders = ','.join(['%s'] * len(asins))
        cursor = self.conn.cursor()
        try:
            cursor.execute(f"SELECT asin FROM books WHERE asin IN ({placeholders})", asins)
            return {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def get_asins_with_recommendations(self) -> set:
        """Return set of source ASINs that already have recommendations stored."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT source_asin FROM recommendations")
            return {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def add_recommendations_bulk(self, rows: list) -> None:
        """Bulk-insert (source_asin, recommended_asin) pairs. Silently ignores duplicates."""
        if not rows:
            return
        cursor = self.conn.cursor()
        try:
            now = datetime.now()
            cursor.executemany("""
                INSERT IGNORE INTO recommendations (source_asin, recommended_asin, created_date)
                VALUES (%s, %s, %s)
            """, [(src, rec, now) for src, rec in rows])
            self.conn.commit()
        finally:
            cursor.close()

    def get_bulk_recommendation_sources(self, asins: list) -> dict:
        """Fetch source book title for each recommended ASIN in one query. Returns dict asin->title."""
        if not asins:
            return {}
        placeholders = ','.join(['%s'] * len(asins))
        cursor = self.conn.cursor(dictionary=True)
        try:
            cursor.execute(f"""
                SELECT r.recommended_asin, b.title
                FROM recommendations r
                JOIN books b ON r.source_asin = b.asin
                WHERE r.recommended_asin IN ({placeholders})
                AND b.is_sample = 1 AND b.is_deleted = 0
            """, asins)
            results = {}
            for row in cursor.fetchall():
                if row['recommended_asin'] not in results:
                    results[row['recommended_asin']] = row['title']
            return results
        finally:
            cursor.close()

    @contextmanager
    def batch_writes(self):
        """
        Context manager that defers auto-commits inside the block.
        A single commit is issued on clean exit; rollback on exception.

        Usage:
            with db.batch_writes():
                db.add_price_history(...)
                db.add_notification(...)
        """
        self._batch_mode = True
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self._batch_mode = False

    def ping_reconnect(self) -> None:
        """Ping the MySQL connection and reconnect if dropped."""
        try:
            self.conn.ping(reconnect=True, attempts=3, delay=2)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"DB reconnect attempt failed: {e}")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
