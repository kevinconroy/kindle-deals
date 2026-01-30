import mysql.connector
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

        # Books table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                asin VARCHAR(20) PRIMARY KEY,
                title VARCHAR(500),
                author VARCHAR(255),
                cover_url VARCHAR(1000),
                date_added DATETIME NOT NULL,
                is_active TINYINT(1) DEFAULT 1
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

        # Price history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                asin VARCHAR(20) NOT NULL,
                price DECIMAL(10,2),
                list_price DECIMAL(10,2),
                check_date DATETIME NOT NULL,
                FOREIGN KEY (asin) REFERENCES books(asin)
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

        self.conn.commit()

    def add_book(self, asin: str, title: str = None, author: str = None,
                 cover_url: str = None) -> bool:
        """
        Add a new book to the database.

        Args:
            asin: Amazon Standard Identification Number
            title: Book title (optional, will be NULL if not provided)
            author: Book author (optional)
            cover_url: URL to book cover image (optional)

        Returns:
            True if book was newly added, False if already existed
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT IGNORE INTO books (asin, title, author, cover_url, date_added, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (asin, title, author, cover_url, datetime.now()))
        self.conn.commit()

        # Log how many rows were affected (0 if already exists due to INSERT IGNORE)
        if cursor.rowcount == 0:
            return False  # Already existed
        return True  # Newly added

    def get_book(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get a book by ASIN.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with book data or None if not found
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM books WHERE asin = %s", (asin,))
        result = cursor.fetchone()
        return result

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
        cursor.execute("""
            UPDATE books
            SET title = %s, author = %s, cover_url = %s
            WHERE asin = %s
        """, (title, author, cover_url, asin))
        self.conn.commit()

    def mark_book_inactive(self, asin: str) -> None:
        """
        Mark a book as inactive (no longer tracking).

        Args:
            asin: Amazon Standard Identification Number
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE books
            SET is_active = 0
            WHERE asin = %s
        """, (asin,))
        self.conn.commit()

    def reactivate_book(self, asin: str) -> None:
        """
        Mark a book as active (resume tracking).

        Args:
            asin: Amazon Standard Identification Number
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE books
            SET is_active = 1
            WHERE asin = %s
        """, (asin,))
        self.conn.commit()

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
        cursor.execute("""
            INSERT INTO price_history (asin, price, list_price, check_date)
            VALUES (%s, %s, %s, %s)
        """, (asin, price, list_price, datetime.now()))
        self.conn.commit()

    def get_latest_price(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent price check for a book.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with price data or None if no history exists
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM price_history
            WHERE asin = %s
            ORDER BY id DESC
            LIMIT 1
        """, (asin,))
        result = cursor.fetchone()
        return result

    def get_previous_price(self, asin: str) -> Optional[float]:
        """
        Get the second-most-recent price for a book (prior day's price).

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Previous price as float or None if no previous price exists
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT price FROM price_history
            WHERE asin = %s
            ORDER BY id DESC
            LIMIT 1 OFFSET 1
        """, (asin,))
        result = cursor.fetchone()
        return float(result['price']) if result and result['price'] is not None else None

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
        cursor.execute("""
            SELECT COUNT(*) as count FROM price_history
            WHERE asin = %s AND check_date >= %s
        """, (asin, deal_day))
        result = cursor.fetchone()
        return result[0] > 0

    def add_notification(self, asin: str, notified_price: float) -> None:
        """
        Add a notification record for a book.

        Args:
            asin: Amazon Standard Identification Number
            notified_price: Price at which notification was sent
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (asin, notified_price, notified_date)
            VALUES (%s, %s, %s)
        """, (asin, notified_price, datetime.now()))
        self.conn.commit()

    def get_last_notification(self, asin: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent notification for a book.

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with notification data or None if no notifications exist
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM notifications
            WHERE asin = %s
            ORDER BY id DESC
            LIMIT 1
        """, (asin,))
        result = cursor.fetchone()
        return result

    def get_active_books(self) -> List[Dict[str, Any]]:
        """
        Get all active books.

        Returns:
            List of dictionaries with book data
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM books WHERE is_active = 1")
        results = cursor.fetchall()
        return results

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

    def get_recommendations(self, source_asin: str) -> List[str]:
        """
        Get all recommended ASINs for a source book.

        Args:
            source_asin: The book to get recommendations for

        Returns:
            List of recommended ASINs
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT recommended_asin FROM recommendations
            WHERE source_asin = %s
        """, (source_asin,))
        results = cursor.fetchall()
        return [row[0] for row in results]

    def has_recommendations(self, source_asin: str) -> bool:
        """
        Check if we've already scraped recommendations for this book.

        Args:
            source_asin: The book to check

        Returns:
            True if recommendations exist, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM recommendations
            WHERE source_asin = %s
        """, (source_asin,))
        count = cursor.fetchone()[0]
        return count > 0

    def get_all_recommended_asins(self) -> Dict[str, str]:
        """
        Get all recommended ASINs with their source book titles.

        Returns:
            Dict mapping recommended_asin -> source_book_title
            (titles are 'Unknown' if not yet fetched from API)
        """
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.recommended_asin, b.title
            FROM recommendations r
            JOIN books b ON r.source_asin = b.asin
            WHERE b.is_active = 1
        """)
        results = cursor.fetchall()
        return {row['recommended_asin']: row['title'] or 'Unknown' for row in results}

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
