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
    def generate_email_html(books: List[Dict[str, Any]]) -> str:
        """
        Generate HTML email content from book data.

        Args:
            books: List of book dictionaries with keys:
                - asin: Amazon Standard Identification Number
                - title: Book title
                - author: Book author (optional)
                - cover_url: URL to book cover (optional)
                - price: Current price
                - list_price: Original list price

        Returns:
            HTML string for email body
        """
        html = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #ff9900;
            border-bottom: 2px solid #ff9900;
            padding-bottom: 10px;
        }
        .book {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            background-color: #f9f9f9;
        }
        .book-content {
            display: table;
            width: 100%;
        }
        .book-cover {
            display: table-cell;
            vertical-align: top;
            width: 150px;
            padding-right: 20px;
        }
        .book-cover img {
            max-width: 150px;
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .book-details {
            display: table-cell;
            vertical-align: top;
        }
        .book-title {
            font-size: 20px;
            font-weight: bold;
            color: #232f3e;
            margin: 0 0 5px 0;
        }
        .book-author {
            font-size: 14px;
            color: #555;
            margin: 0 0 15px 0;
        }
        .price-info {
            margin: 15px 0;
        }
        .current-price {
            font-size: 24px;
            font-weight: bold;
            color: #b12704;
        }
        .list-price {
            font-size: 14px;
            color: #555;
            text-decoration: line-through;
            margin-left: 10px;
        }
        .savings {
            display: inline-block;
            background-color: #c45500;
            color: white;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 10px;
        }
        .previous-price {
            font-size: 14px;
            color: #888;
            margin-left: 10px;
        }
        .price-drop {
            display: inline-block;
            background-color: #067d62;
            color: white;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 10px;
        }
        .buy-button {
            display: inline-block;
            background-color: #ff9900;
            color: #111;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 4px;
            font-weight: bold;
            margin-top: 10px;
        }
        .buy-button:hover {
            background-color: #ec8a00;
        }
        .match-reason {
            font-size: 13px;
            color: #067d62;
            margin: 8px 0 12px 0;
            font-weight: 600;
            padding: 4px 0;
        }
        .match-reason::before {
            content: "✓ ";
            font-weight: bold;
        }
    </style>
</head>
<body>
    <h1>Kindle Deals Alert</h1>
    <p>The following Kindle books on your watchlist are now on sale:</p>
"""

        for book in books:
            asin = book['asin']
            title = html_lib.escape(book['title'])
            author = html_lib.escape(book.get('author', 'Unknown Author'))
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

            html += f"""
    <div class="book">
        <div class="book-content">
"""

            # Add cover image if available
            if cover_url:
                html += f"""
            <div class="book-cover">
                <img src="{cover_url}" alt="{title}">
            </div>
"""

            html += f"""
            <div class="book-details">
                <div class="book-title">{title}</div>
"""

            # Add author if available
            if author:
                html += f"""
                <div class="book-author">by {author}</div>
"""

            # Add match reason if available (for daily deals)
            match_reason = book.get('match_reason')
            if match_reason:
                html += f"""
                <div class="match-reason">{html_lib.escape(match_reason)}</div>
"""

            # Format price display
            if current_price == 0:
                price_display = "FREE"
            else:
                price_display = f"${current_price:.2f}"

            html += f"""
                <div class="price-info">
                    <div style="margin-bottom: 8px;">
                        <span class="current-price">{price_display}</span>
"""

            # Show list price and overall savings
            if list_price > 0 and list_price != current_price:
                html += f"""
                        <span class="list-price">List: ${list_price:.2f}</span>
                        <span class="savings">Save {savings_percent}%</span>
"""

            html += f"""
                    </div>
"""

            # Show previous price and price drop if available
            if previous_price and price_drop and price_drop > 0:
                html += f"""
                    <div style="font-size: 13px; color: #555;">
                        <span class="previous-price">Was: ${previous_price:.2f}</span>
                        <span class="price-drop">↓ ${price_drop:.2f} ({price_drop_percent}%)</span>
                    </div>
"""

            html += f"""
                </div>
                <a href="{amazon_link}" class="buy-button">Buy now on Amazon</a>
            </div>
        </div>
    </div>
"""

        html += """
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">
        This is an automated notification from your Kindle Deals Monitor.
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
