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
    cursor.execute("TRUNCATE TABLE purchases")
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


def test_get_unchecked_recommendation_asins(clean_db):
    """Test getting recommendation ASINs not yet checked today."""
    # Add sample books
    clean_db.add_book(asin='B001', title='Sample Book 1')
    clean_db.add_book(asin='B002', title='Sample Book 2')

    # Add recommendations
    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B001', 'R002')
    clean_db.add_recommendation('B002', 'R003')

    # All three should be unchecked
    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert set(unchecked) == {'R001', 'R002', 'R003'}

    # Mark one as checked today
    clean_db.add_deal_check('R001', was_deal=False, notified=False)

    # Now only two should be unchecked
    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert set(unchecked) == {'R002', 'R003'}


def test_get_unchecked_recommendation_asins_force_ignores_todays_checks(clean_db):
    """--force is documented as "check even if already checked today".

    Phase 1 and Phase 2 honor it; without this, Phase 3 silently re-checked only
    the ASINs missed by an earlier run on the same day.
    """
    clean_db.add_book(asin='B001', title='Sample Book 1')
    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B001', 'R002')

    clean_db.add_deal_check('R001', was_deal=False, notified=False)

    assert set(clean_db.get_unchecked_recommendation_asins()) == {'R002'}
    assert set(clean_db.get_unchecked_recommendation_asins(force=True)) == {'R001', 'R002'}


def test_get_unchecked_recommendation_asins_excludes_deleted_sources(clean_db):
    """Test that recommendations from deleted source books are excluded."""
    clean_db.add_book(asin='B001', title='Active Sample')
    clean_db.add_book(asin='B002', title='Deleted Sample')
    clean_db.mark_book_deleted('B002')

    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B002', 'R002')

    unchecked = clean_db.get_unchecked_recommendation_asins()
    assert unchecked == ['R001']


def test_add_recommendation_book_new(clean_db):
    """Test adding a new recommendation book."""
    clean_db.add_recommendation_book('R001', 'Rec Book', 'Rec Author', 'https://example.com/cover.jpg')

    book = clean_db.get_book('R001')
    assert book is not None
    assert book['title'] == 'Rec Book'
    assert book['author'] == 'Rec Author'
    assert book['is_sample'] == 0
    assert book['is_recommendation'] == 1


def test_add_recommendation_book_existing_sample(clean_db):
    """Test that adding a recommendation book doesn't override existing sample."""
    # Book already exists as a sample
    clean_db.add_book(asin='B001', title='My Sample', author='Original Author')

    # Try to add as recommendation - should update metadata but keep is_sample=1
    clean_db.add_recommendation_book('B001', 'Updated Title', 'Updated Author', 'https://example.com/new.jpg')

    book = clean_db.get_book('B001')
    assert book['is_sample'] == 1  # Preserved
    assert book['is_recommendation'] == 0  # Not changed to recommendation
    assert book['title'] == 'Updated Title'  # Metadata updated


def test_add_recommendation_book_updates_metadata(clean_db):
    """Test that re-adding a recommendation book updates metadata."""
    clean_db.add_recommendation_book('R001', None, None, None)
    clean_db.add_recommendation_book('R001', 'Now Has Title', 'Now Has Author', 'https://example.com/cover.jpg')

    book = clean_db.get_book('R001')
    assert book['title'] == 'Now Has Title'
    assert book['author'] == 'Now Has Author'


def test_get_recommendation_source(clean_db):
    """Test getting source book title for a recommendation."""
    clean_db.add_book(asin='B001', title='The Way of Kings', author='Brandon Sanderson')
    clean_db.add_recommendation('B001', 'R001')

    source_title = clean_db.get_recommendation_source('R001')
    assert source_title == 'The Way of Kings'


def test_get_recommendation_source_not_found(clean_db):
    """Test getting source for a non-existent recommendation."""
    source_title = clean_db.get_recommendation_source('NOTEXIST')
    assert source_title is None


def test_get_checked_today_asins(clean_db):
    """Test bulk fetch of ASINs already checked today."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_price_history('B001', 9.99, 19.99)

    from datetime import datetime
    deal_day = datetime.combine(datetime.now().date(), datetime.min.time())
    checked = clean_db.get_checked_today_asins(deal_day)
    assert 'B001' in checked
    assert 'B002' not in checked


def test_get_bulk_previous_prices(clean_db):
    """Test bulk fetch of previous prices for multiple ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_price_history('B001', 9.99, 19.99)
    clean_db.add_price_history('B001', 7.99, 19.99)
    clean_db.add_price_history('B002', 3.99, 14.99)

    prices = clean_db.get_bulk_previous_prices(['B001', 'B002', 'B003'])
    assert prices['B001'] == 7.99
    assert prices['B002'] == 3.99
    assert 'B003' not in prices


def test_get_bulk_last_notifications(clean_db):
    """Test bulk fetch of last notification prices for multiple ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')
    clean_db.add_notification('B001', 9.99)
    clean_db.add_notification('B001', 7.99)
    clean_db.add_notification('B002', 3.99)

    notifications = clean_db.get_bulk_last_notifications(['B001', 'B002', 'B003'])
    assert notifications['B001'] == 7.99
    assert notifications['B002'] == 3.99
    assert 'B003' not in notifications


def test_get_existing_asins(clean_db):
    """Test bulk fetch of known ASINs."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_book(asin='B002', title='Book 2')

    known = clean_db.get_existing_asins(['B001', 'B002', 'B999'])
    assert 'B001' in known
    assert 'B002' in known
    assert 'B999' not in known


def test_add_recommendations_bulk(clean_db):
    """Test bulk recommendation insert."""
    clean_db.add_book(asin='B001', title='Book 1')
    clean_db.add_recommendations_bulk([('B001', 'R001'), ('B001', 'R002')])
    recs = clean_db.get_recommendations('B001')
    assert set(recs) == {'R001', 'R002'}


def test_get_bulk_recommendation_sources(clean_db):
    """Test bulk fetch of recommendation source titles."""
    clean_db.add_book(asin='B001', title='The Way of Kings')
    clean_db.add_recommendation('B001', 'R001')
    clean_db.add_recommendation('B001', 'R002')

    sources = clean_db.get_bulk_recommendation_sources(['R001', 'R002', 'R999'])
    assert sources['R001'] == 'The Way of Kings'
    assert sources['R002'] == 'The Way of Kings'
    assert 'R999' not in sources


def test_ping_reconnect(clean_db):
    """Test ping_reconnect does not raise."""
    clean_db.ping_reconnect()  # Should not raise


def test_batch_writes_commits_atomically(clean_db):
    """batch_writes context manager should commit all writes together."""
    clean_db.add_book(asin='B001', title='Book')
    with clean_db.batch_writes():
        clean_db.add_price_history('B001', 2.99, 14.99)
        clean_db.add_notification('B001', 2.99)
    assert clean_db.get_latest_price('B001') is not None
    assert clean_db.get_last_notification('B001') is not None


def test_batch_writes_rolls_back_on_error(clean_db):
    """batch_writes should rollback if an error occurs mid-batch."""
    clean_db.add_book(asin='B001', title='Book')
    with pytest.raises(RuntimeError):
        with clean_db.batch_writes():
            clean_db.add_price_history('B001', 2.99, 14.99)
            raise RuntimeError("simulated error")
    assert clean_db.get_latest_price('B001') is None


def test_add_and_is_purchased(clean_db):
    """add_purchase records a purchase and is_purchased detects it."""
    clean_db.add_book('B0PURCHASE1', title='Bought Book')
    assert clean_db.is_purchased('B0PURCHASE1') is False

    clean_db.add_purchase('B0PURCHASE1', 3.99, points_applied=3.99)
    assert clean_db.is_purchased('B0PURCHASE1') is True


def test_add_purchase_is_idempotent(clean_db):
    """add_purchase twice for the same asin does not error and stays single."""
    clean_db.add_book('B0PURCHASE2', title='Bought Twice')
    clean_db.add_purchase('B0PURCHASE2', 2.99, points_applied=2.99)
    clean_db.add_purchase('B0PURCHASE2', 2.99, points_applied=2.99)

    cursor = clean_db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM purchases WHERE asin = %s", ('B0PURCHASE2',))
    assert cursor.fetchone()[0] == 1
    cursor.close()


def test_sample_cleanup_candidates_include_purchases_and_dual_state(clean_db):
    """Purchased books and dual-state samples are candidates until their sample is removed."""
    clean_db.add_book('B0BOUGHT01', title='Bought')
    clean_db.add_purchase('B0BOUGHT01', 2.99, points_applied=2.99)
    clean_db.mark_book_deleted('B0BOUGHT01')  # check_deals marks purchases deleted

    clean_db.add_book('B0DUAL0001', title='Dual')
    clean_db.set_has_owned_copy('B0DUAL0001', True)

    clean_db.add_book('B0PLAIN001', title='Just a sample')

    asins = {b['asin'] for b in clean_db.get_sample_cleanup_candidates()}
    assert asins == {'B0BOUGHT01', 'B0DUAL0001'}


def test_sample_cleanup_candidates_include_deleted_dual_state(clean_db):
    """A flagged sample marked deleted by an earlier sync is still a candidate."""
    clean_db.add_book('B0DUAL0003', title='The Running Man')
    clean_db.set_has_owned_copy('B0DUAL0003', True)
    clean_db.mark_book_deleted('B0DUAL0003')

    assert [b['asin'] for b in clean_db.get_sample_cleanup_candidates()] == ['B0DUAL0003']


def test_mark_sample_removed_drops_candidate(clean_db):
    clean_db.add_book('B0DUAL0002', title='Dual')
    clean_db.set_has_owned_copy('B0DUAL0002', True)

    clean_db.mark_sample_removed('B0DUAL0002')

    assert clean_db.get_sample_cleanup_candidates() == []
    assert clean_db.get_samples_with_owned_copies() == []
    book = clean_db.get_book('B0DUAL0002')
    assert book['sample_removed_date'] is not None
    assert book['is_deleted'] == 1


def test_clear_unowned_flag_returns_book_to_deal_tracking(clean_db):
    """A false has_owned_copy (e.g. an expired borrow) is cleared so deals are checked again."""
    clean_db.add_book('B0BORROW01', title='Borrowed once')
    clean_db.set_has_owned_copy('B0BORROW01', True)

    assert clean_db.clear_unowned_flag('B0BORROW01') is True

    assert clean_db.get_book('B0BORROW01')['has_owned_copy'] == 0
    assert 'B0BORROW01' in {b['asin'] for b in clean_db.get_sample_books()}


def test_clear_unowned_flag_never_touches_purchases(clean_db):
    clean_db.add_book('B0BOUGHT02', title='Bought')
    clean_db.set_has_owned_copy('B0BOUGHT02', True)
    clean_db.add_purchase('B0BOUGHT02', 2.99, points_applied=2.99)

    assert clean_db.clear_unowned_flag('B0BOUGHT02') is False
    assert clean_db.get_book('B0BOUGHT02')['has_owned_copy'] == 1
