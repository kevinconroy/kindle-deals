import pytest
from src.email_notifier import EmailNotifier


def test_generate_email_html_single_book():
    """Test that generate_email_html creates proper HTML for a single book."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'The Great Gatsby',
            'author': 'F. Scott Fitzgerald',
            'cover_url': 'https://example.com/cover.jpg',
            'price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    # Verify HTML structure
    assert '<html>' in html
    assert '</html>' in html
    assert '<body>' in html
    assert '</body>' in html

    # Verify book fields appear in output
    assert 'The Great Gatsby' in html
    assert 'F. Scott Fitzgerald' in html
    assert 'https://example.com/cover.jpg' in html
    assert '$2.99' in html
    assert '$9.99' in html

    # Verify Amazon link format
    assert 'https://www.amazon.com/dp/B001234567' in html

    # Verify savings calculation (70% off)
    assert '70%' in html


def test_generate_email_html_multiple_books():
    """Test that generate_email_html handles multiple books."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'Book One',
            'author': 'Author One',
            'cover_url': 'https://example.com/cover1.jpg',
            'price': 1.99,
            'list_price': 9.99,
        },
        {
            'asin': 'B007654321',
            'title': 'Book Two',
            'author': 'Author Two',
            'cover_url': 'https://example.com/cover2.jpg',
            'price': 3.99,
            'list_price': 14.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    # Verify both books appear
    assert 'Book One' in html
    assert 'Book Two' in html
    assert 'Author One' in html
    assert 'Author Two' in html

    # Verify both ASINs in Amazon links
    assert 'https://www.amazon.com/dp/B001234567' in html
    assert 'https://www.amazon.com/dp/B007654321' in html

    # Verify both prices
    assert '$1.99' in html
    assert '$3.99' in html


def test_generate_email_html_no_author():
    """Test that generate_email_html handles books without author."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'Mystery Book',
            'author': None,
            'cover_url': 'https://example.com/cover.jpg',
            'price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    # Should still generate valid HTML
    assert '<html>' in html
    assert 'Mystery Book' in html
    assert 'https://www.amazon.com/dp/B001234567' in html


def test_generate_email_html_no_cover():
    """Test that generate_email_html handles books without cover URL."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'Coverless Book',
            'author': 'Some Author',
            'cover_url': None,
            'price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    # Should still generate valid HTML
    assert '<html>' in html
    assert 'Coverless Book' in html
    assert 'https://www.amazon.com/dp/B001234567' in html


def test_generate_email_html_shows_previous_price():
    """Test that previous price is shown even without a price drop."""
    books = [
        {
            'asin': 'B001234567',
            'title': 'Test Book',
            'author': 'Test Author',
            'cover_url': 'https://example.com/cover.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
            'previous_price': 2.99,  # Same price - no drop
        }
    ]

    html = EmailNotifier.generate_email_html(books)
    assert 'Last seen' in html
    assert '$2.99' in html


def test_generate_email_html_two_sections():
    """Test email with both tracked and recommended deals."""
    tracked = [
        {
            'asin': 'B001',
            'title': 'Tracked Book',
            'author': 'Author One',
            'cover_url': 'https://example.com/cover1.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]
    recommended = [
        {
            'asin': 'R001',
            'title': 'Recommended Book',
            'author': 'Author Two',
            'cover_url': 'https://example.com/cover2.jpg',
            'current_price': 1.99,
            'list_price': 12.99,
            'match_reason': 'Recommended from: Tracked Book',
        }
    ]

    html = EmailNotifier.generate_email_html(tracked, recommended_deals=recommended)

    assert 'Tracked Deals' in html
    assert 'Recommended Deals' in html
    assert 'Tracked Book' in html
    assert 'Recommended Book' in html
    assert 'No tracked deals today' not in html


def test_generate_email_html_no_tracked_deals():
    """Test email shows 'No tracked deals today' when tracked section is empty."""
    recommended = [
        {
            'asin': 'R001',
            'title': 'Recommended Book',
            'author': 'Author Two',
            'cover_url': 'https://example.com/cover2.jpg',
            'current_price': 1.99,
            'list_price': 12.99,
            'match_reason': 'Recommended from: Some Book',
        }
    ]

    html = EmailNotifier.generate_email_html([], recommended_deals=recommended)

    assert 'No tracked deals today' in html
    assert 'Recommended Deals' in html
    assert 'Recommended Book' in html


def test_generate_email_html_no_recommended_deals():
    """Test email omits recommended section when empty."""
    tracked = [
        {
            'asin': 'B001',
            'title': 'Tracked Book',
            'author': 'Author One',
            'cover_url': 'https://example.com/cover1.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(tracked, recommended_deals=[])

    assert 'Tracked Deals' in html
    assert 'Tracked Book' in html
    assert 'Recommended Deals' not in html


def test_generate_email_html_backward_compatible():
    """Test that calling without recommended_deals works as before (no section headers)."""
    books = [
        {
            'asin': 'B001',
            'title': 'Test Book',
            'author': 'Author',
            'cover_url': 'https://example.com/cover.jpg',
            'current_price': 2.99,
            'list_price': 9.99,
        }
    ]

    html = EmailNotifier.generate_email_html(books)

    assert 'Test Book' in html
    # No section headers in backward-compatible mode
    assert 'Tracked Deals' not in html
    assert 'Recommended Deals' not in html


def test_auto_purchased_book_shows_badge_and_read_now():
    books = [{
        'asin': 'B0AUTO0001',
        'title': 'Auto Bought Novel',
        'author': 'A. Writer',
        'cover_url': 'https://example.com/c.jpg',
        'current_price': 3.99,
        'list_price': 12.99,
        'auto_purchased': True,
        'points_applied': 3.99,
    }]
    html = EmailNotifier.generate_email_html(books)
    assert 'Auto-purchased' in html
    assert 'Read now' in html


def test_non_purchased_book_has_no_badge():
    books = [{
        'asin': 'B0NORMAL01',
        'title': 'Normal Deal',
        'author': 'B. Writer',
        'cover_url': '',
        'current_price': 1.99,
        'list_price': 9.99,
    }]
    html = EmailNotifier.generate_email_html(books)
    assert 'Auto-purchased' not in html
    assert 'Buy now on Amazon' in html
