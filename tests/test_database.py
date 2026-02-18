import pytest
import mysql.connector
from datetime import datetime
from src.database import Database


@pytest.fixture
def db():
    """Create a test database instance."""
    # Use test database
    test_db = Database(
        host='localhost',
        user='root',
        password='',
        database='kindle_deals_test'
    )
    yield test_db
    # Cleanup: drop all data after tests
    test_db.close()


@pytest.fixture
def clean_db(db):
    """Provide a clean database for each test."""
    # Clear all tables before each test
    cursor = db.conn.cursor()
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    cursor.execute("TRUNCATE TABLE deal_checks")
    cursor.execute("TRUNCATE TABLE recommendations")
    cursor.execute("TRUNCATE TABLE notifications")
    cursor.execute("TRUNCATE TABLE price_history")
    cursor.execute("TRUNCATE TABLE books")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    db.conn.commit()
    yield db


def test_database_init_creates_database():
    """Test that database is created if it doesn't exist."""
    db = Database(
        host='localhost',
        user='root',
        password='',
        database='kindle_deals_test'
    )
    assert db.conn is not None
    db.close()


def test_database_creates_tables(clean_db):
    """Test that all required tables are created."""
    cursor = clean_db.conn.cursor()

    # Check books table exists
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'kindle_deals_test'
        AND table_name = 'books'
    """)
    assert cursor.fetchone()[0] == 1

    # Check price_history table exists
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'kindle_deals_test'
        AND table_name = 'price_history'
    """)
    assert cursor.fetchone()[0] == 1

    # Check notifications table exists
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'kindle_deals_test'
        AND table_name = 'notifications'
    """)
    assert cursor.fetchone()[0] == 1


def test_add_book(clean_db):
    """Test adding a book to the database."""
    clean_db.add_book(
        asin='B001234567',
        title='Test Book',
        author='Test Author',
        cover_url='https://example.com/cover.jpg'
    )

    book = clean_db.get_book('B001234567')
    assert book is not None
    assert book['asin'] == 'B001234567'
    assert book['title'] == 'Test Book'
    assert book['author'] == 'Test Author'
    assert book['cover_url'] == 'https://example.com/cover.jpg'
    assert book['is_sample'] == 1
    assert book['is_deleted'] == 0
    assert book['date_added'] is not None


def test_get_book_not_found(clean_db):
    """Test getting a book that doesn't exist."""
    book = clean_db.get_book('NOTFOUND')
    assert book is None


def test_add_price_history(clean_db):
    """Test adding price history for a book."""
    # First add a book
    clean_db.add_book(
        asin='B001234567',
        title='Test Book',
        author='Test Author'
    )

    # Add price history
    clean_db.add_price_history(
        asin='B001234567',
        price=9.99,
        list_price=14.99
    )

    # Get latest price
    price_info = clean_db.get_latest_price('B001234567')
    assert price_info is not None
    assert float(price_info['price']) == 9.99
    assert float(price_info['list_price']) == 14.99
    assert price_info['check_date'] is not None


def test_get_latest_price_no_history(clean_db):
    """Test getting latest price when no history exists."""
    # Add book without price history
    clean_db.add_book(
        asin='B001234567',
        title='Test Book'
    )

    price_info = clean_db.get_latest_price('B001234567')
    assert price_info is None


def test_add_notification(clean_db):
    """Test adding a notification."""
    # First add a book
    clean_db.add_book(
        asin='B001234567',
        title='Test Book'
    )

    # Add notification
    clean_db.add_notification(
        asin='B001234567',
        notified_price=9.99
    )

    # Get last notification
    notification = clean_db.get_last_notification('B001234567')
    assert notification is not None
    assert float(notification['notified_price']) == 9.99
    assert notification['notified_date'] is not None


def test_get_last_notification_none(clean_db):
    """Test getting last notification when none exists."""
    # Add book without notifications
    clean_db.add_book(
        asin='B001234567',
        title='Test Book'
    )

    notification = clean_db.get_last_notification('B001234567')
    assert notification is None


def test_get_sample_books(clean_db):
    """Test getting all sample books."""
    # Add multiple books
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_book(asin='B003', title='Book 3')

    books = clean_db.get_sample_books()
    assert len(books) == 3
    assert all(book['is_sample'] == 1 for book in books)
    assert all(book['is_deleted'] == 0 for book in books)


def test_get_sample_books_excludes_deleted(clean_db):
    """Test that get_sample_books excludes deleted books."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.mark_book_deleted('B002')

    books = clean_db.get_sample_books()
    assert len(books) == 1
    assert books[0]['asin'] == 'B001'


def test_get_sample_books_empty(clean_db):
    """Test getting sample books when database is empty."""
    books = clean_db.get_sample_books()
    assert len(books) == 0


def test_multiple_price_history_entries(clean_db):
    """Test that get_latest_price returns most recent entry."""
    # Add book
    clean_db.add_book(asin='B001234567', title='Test Book')

    # Add multiple price history entries
    clean_db.add_price_history(asin='B001234567', price=14.99, list_price=19.99)
    clean_db.add_price_history(asin='B001234567', price=9.99, list_price=19.99)
    clean_db.add_price_history(asin='B001234567', price=7.99, list_price=19.99)

    # Should get the most recent (last added)
    price_info = clean_db.get_latest_price('B001234567')
    assert float(price_info['price']) == 7.99


def test_multiple_notifications(clean_db):
    """Test that get_last_notification returns most recent entry."""
    # Add book
    clean_db.add_book(asin='B001234567', title='Test Book')

    # Add multiple notifications
    clean_db.add_notification(asin='B001234567', notified_price=14.99)
    clean_db.add_notification(asin='B001234567', notified_price=9.99)

    # Should get the most recent
    notification = clean_db.get_last_notification('B001234567')
    assert float(notification['notified_price']) == 9.99


def test_add_owned_book(clean_db):
    """Test adding an owned (non-sample) book."""
    clean_db.add_book(asin='B001234567', title='Owned Book', is_sample=False)

    book = clean_db.get_book('B001234567')
    assert book['is_sample'] == 0
    assert book['is_deleted'] == 0


def test_mark_book_deleted(clean_db):
    """Test marking a book as deleted."""
    clean_db.add_book(asin='B001', title='Test Book')
    clean_db.mark_book_deleted('B001')

    book = clean_db.get_book('B001')
    assert book['is_deleted'] == 1
    assert book['is_sample'] == 1  # sample status preserved


def test_undelete_book(clean_db):
    """Test undeleting a book."""
    clean_db.add_book(asin='B001', title='Test Book')
    clean_db.mark_book_deleted('B001')
    clean_db.undelete_book('B001')

    book = clean_db.get_book('B001')
    assert book['is_deleted'] == 0


def test_update_book_sample_status(clean_db):
    """Test updating a book's sample status."""
    clean_db.add_book(asin='B001', title='Test Book', is_sample=True)
    clean_db.update_book_sample_status('B001', is_sample=False)

    book = clean_db.get_book('B001')
    assert book['is_sample'] == 0


def test_foreign_key_constraint(clean_db):
    """Test that foreign key constraints are enforced."""
    # Try to add price history for non-existent book
    with pytest.raises(mysql.connector.IntegrityError):
        clean_db.add_price_history(
            asin='NOTEXIST',
            price=9.99,
            list_price=14.99
        )
