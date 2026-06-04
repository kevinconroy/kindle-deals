import smtplib
import html as html_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any


class EmailNotifier:
    def __init__(self, smtp_server: str, smtp_port: int,
                 from_address: str, password: str):
        """
        Initialize email notifier with SMTP settings.

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port
            from_address: Email address to send from
            password: SMTP password
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.from_address = from_address
        self.password = password

    @staticmethod
    def _generate_book_html(book: Dict[str, Any]) -> str:
        """
        Generate HTML for a single book card.

        Args:
            book: Book dictionary with keys:
                - asin: Amazon Standard Identification Number
                - title: Book title
                - author: Book author (optional)
                - cover_url: URL to book cover (optional)
                - current_price or price: Current price
                - list_price: Original list price
                - previous_price: Previous seen price (optional)
                - match_reason: Why this book was matched (optional)

        Returns:
            HTML string for one book card
        """
        asin = book['asin']
        title = html_lib.escape(book['title'])
        author = html_lib.escape(book.get('author') or 'Unknown Author')
        cover_url = book.get('cover_url', '')
        current_price = book.get('current_price') or book.get('price', 0)
        list_price = book.get('list_price', 0)
        previous_price = book.get('previous_price')

        # Handle free books (price could be 0 or None)
        if current_price is None:
            current_price = 0

        # Calculate savings percentage from list price
        if list_price and list_price > 0:
            savings_percent = int(((list_price - current_price) / list_price) * 100)
        else:
            savings_percent = 0

        # Calculate price drop from previous price
        price_drop = None
        price_drop_percent = None
        if previous_price and previous_price > current_price:
            price_drop = previous_price - current_price
            price_drop_percent = int((price_drop / previous_price) * 100)

        # Amazon link
        amazon_link = f"https://www.amazon.com/dp/{asin}"

        book_html = f"""
    <div class="book">
        <div class="book-content">
"""

        # Add cover image if available
        if cover_url:
            book_html += f"""
            <div class="book-cover">
                <img src="{cover_url}" alt="{title}">
            </div>
"""

        book_html += f"""
            <div class="book-details">
                <div class="book-title">{title}</div>
"""

        # Add author if available
        if author:
            book_html += f"""
                <div class="book-author">by {author}</div>
"""

        # Add match reason if available (for daily deals)
        match_reason = book.get('match_reason')
        if match_reason:
            book_html += f"""
                <div class="match-reason">{html_lib.escape(match_reason)}</div>
"""

        # Auto-purchased badge
        auto_purchased = book.get('auto_purchased')
        if auto_purchased:
            book_html += """
                <div class="auto-purchased">Auto-purchased</div>
"""

        # Format price display
        if current_price == 0:
            price_display = "FREE"
        else:
            price_display = f"${current_price:.2f}"

        book_html += f"""
                <div class="price-info">
                    <div style="margin-bottom: 8px;">
                        <span class="current-price">{price_display}</span>
"""

        # Show list price and overall savings
        if list_price > 0 and list_price != current_price:
            book_html += f"""
                        <span class="list-price">List: ${list_price:.2f}</span>
                        <span class="savings">Save {savings_percent}%</span>
"""

        book_html += f"""
                    </div>
"""

        # Show previous price when available
        if previous_price is not None and previous_price > 0:
            book_html += f"""
                    <div style="font-size: 13px; color: #888; margin-top: 4px;">
                        <span class="previous-price">Last seen: ${previous_price:.2f}</span>
"""
            if price_drop and price_drop > 0:
                book_html += f"""
                        <span class="price-drop">↓ ${price_drop:.2f} ({price_drop_percent}%)</span>
"""
            book_html += """
                    </div>
"""

        book_html += f"""
                </div>
                <a href="{amazon_link}" class="buy-button">{'Read now' if auto_purchased else 'Buy now on Amazon'}</a>
            </div>
        </div>
    </div>
"""
        return book_html

    @staticmethod
    def generate_email_html(books: List[Dict[str, Any]], recommended_deals: List[Dict[str, Any]] = None) -> str:
        """
        Generate HTML email content from book data.

        When recommended_deals is None, uses the flat layout (backward compatible).
        When recommended_deals is provided (even if empty), uses the two-section layout
        with "Tracked Deals" and "Recommended Deals" sections.

        Args:
            books: List of book dictionaries with keys:
                - asin: Amazon Standard Identification Number
                - title: Book title
                - author: Book author (optional)
                - cover_url: URL to book cover (optional)
                - current_price or price: Current price
                - list_price: Original list price
            recommended_deals: Optional list of recommended book dictionaries.
                When provided, enables the two-section layout.

        Returns:
            HTML string for email body
        """
        two_section_mode = recommended_deals is not None

        css_extra = ""
        if two_section_mode:
            css_extra = """
        h2 {
            color: #232f3e;
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #e0e0e0;
        }
        .no-deals {
            color: #888;
            font-style: italic;
            padding: 16px 0;
        }
"""

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #ff9900;
            border-bottom: 2px solid #ff9900;
            padding-bottom: 10px;
            font-size: 24px;
            margin-bottom: 5px;
        }}
        .book {{
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin: 16px 0;
            background-color: #ffffff;
        }}
        .book-content {{
            display: table;
            width: 100%;
        }}
        .book-cover {{
            display: table-cell;
            vertical-align: top;
            width: 120px;
            padding-right: 20px;
        }}
        .book-cover img {{
            max-width: 120px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.12);
        }}
        .book-details {{
            display: table-cell;
            vertical-align: top;
        }}
        .book-title {{
            font-size: 18px;
            font-weight: bold;
            color: #232f3e;
            margin: 0 0 4px 0;
            line-height: 1.3;
        }}
        .book-author {{
            font-size: 14px;
            color: #555;
            margin: 0 0 10px 0;
        }}
        .price-info {{
            margin: 10px 0;
        }}
        .current-price {{
            font-size: 22px;
            font-weight: bold;
            color: #b12704;
        }}
        .list-price {{
            font-size: 14px;
            color: #888;
            text-decoration: line-through;
            margin-left: 8px;
        }}
        .savings {{
            display: inline-block;
            background-color: #c45500;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }}
        .previous-price {{
            font-size: 13px;
            color: #888;
        }}
        .price-drop {{
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 3px 7px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }}
        .buy-button {{
            display: inline-block;
            background-color: #ff9900;
            color: #ffffff;
            padding: 10px 24px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            margin-top: 12px;
            letter-spacing: 0.3px;
        }}
        .buy-button:hover {{
            background-color: #ec8a00;
        }}
        .buy-button:active {{
            color: #ffffff;
        }}
        .match-reason {{
            font-size: 13px;
            color: #067d62;
            margin: 6px 0 10px 0;
            font-weight: 600;
            padding: 4px 0;
        }}
        .match-reason::before {{
            content: "\\2713  ";
            font-weight: bold;
        }}
        .auto-purchased {{
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin: 6px 0;
        }}{css_extra}
    </style>
</head>
<body>
    <h1>Kindle Deals Alert</h1>
"""

        if two_section_mode:
            # Two-section layout
            html += """
    <h2>Tracked Deals</h2>
"""
            if books:
                for book in books:
                    html += EmailNotifier._generate_book_html(book)
            else:
                html += """
    <p class="no-deals">No tracked deals today</p>
"""

            if recommended_deals:
                html += """
    <h2>Recommended Deals</h2>
"""
                for book in recommended_deals:
                    html += EmailNotifier._generate_book_html(book)
        else:
            # Flat layout (backward compatible)
            html += """
    <p style="color: #555; margin-top: 5px;">The following Kindle books on your watchlist are now on sale:</p>
"""
            for book in books:
                html += EmailNotifier._generate_book_html(book)

        html += """
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #e0e0e0;">
    <p style="font-size: 11px; color: #999; text-align: center;">
        Kindle Deals Monitor &middot; Automated notification
    </p>
</body>
</html>
"""
        return html

    def send_email(self, to_address: str, subject: str, html_content: str) -> None:
        """
        Send an HTML email via SMTP.

        Args:
            to_address: Recipient email address
            subject: Email subject line
            html_content: HTML content for email body
        """
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_address
        msg['To'] = to_address

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.from_address, self.password)
            server.send_message(msg)
