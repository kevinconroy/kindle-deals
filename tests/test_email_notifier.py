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
