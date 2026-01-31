#!/usr/bin/env python3
"""
Test script for email notifications.

This script sends a test email notification with sample Kindle book deals
to verify that email configuration is working correctly.
"""

import argparse
import sys
from config import Config
from email_notifier import EmailNotifier


def send_test_email(config: Config) -> None:
    """
    Send a test email notification with sample book data.

    Args:
        config: Configuration object with email settings

    Raises:
        ValueError: If required email configuration is missing
        smtplib.SMTPException: If email sending fails
    """
    # Create test book data
    test_books = [
        {
            'asin': 'B01234ABCD',
            'title': 'The Art of Computer Programming, Vol. 1',
            'author': 'Donald Knuth',
            'cover_url': 'https://m.media-amazon.com/images/I/41f5MZ8Y2JL.jpg',
            'current_price': 1.99,
            'list_price': 19.99,
            'previous_price': 4.99,
            'match_reason': 'Same author: Donald Knuth'
        },
        {
            'asin': 'B01234EFGH',
            'title': 'Clean Code: A Handbook of Agile Software Craftsmanship',
            'author': 'Robert C. Martin',
            'cover_url': 'https://m.media-amazon.com/images/I/41xShlnTZTL.jpg',
            'current_price': 2.99,
            'list_price': 29.99,
            'previous_price': 9.99,
            'match_reason': 'Same series: Clean Code'
        },
        {
            'asin': 'B01234IJKL',
            'title': 'Design Patterns: Elements of Reusable Object-Oriented Software',
            'author': 'Erich Gamma',
            'cover_url': 'https://m.media-amazon.com/images/I/51szD9HC9pL.jpg',
            'current_price': 3.99,
            'list_price': 39.99,
            'previous_price': 3.99,
            'match_reason': 'Recommended from: Code Complete'
        }
    ]

    # Get email configuration
    smtp_server = config.get('email.smtp_server')
    smtp_port = config.get('email.smtp_port', 587)
    from_address = config.get('email.from_address')
    to_address = config.get('email.to_address')

    # Validate required configuration
    if not smtp_server:
        raise ValueError("email.smtp_server not configured")
    if not from_address:
        raise ValueError("email.from_address not configured")
    if not to_address:
        raise ValueError("email.to_address not configured")

    # Get password from environment variable via config
    password = config.get_email_password()

    # Create email notifier
    notifier = EmailNotifier(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        from_address=from_address,
        password=password
    )

    # Generate email HTML
    html_content = EmailNotifier.generate_email_html(test_books)

    # Send test email
    print(f"Sending test email to {to_address}...")
    notifier.send_email(
        to_address=to_address,
        subject="Test: Kindle Deals Alert",
        html_content=html_content
    )
    print("Test email sent successfully!")


def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description='Test email notifications for Kindle Deals Monitor'
    )
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Send test email with sample book data'
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = Config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Send test email
    if args.test:
        try:
            send_test_email(config)
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error sending test email: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Use --test flag to send a test email")
        parser.print_help()


if __name__ == '__main__':
    main()
