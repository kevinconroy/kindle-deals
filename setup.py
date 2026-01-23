#!/usr/bin/env python3
"""
Interactive setup script for Kindle Deals Monitor.

Guides users through initial configuration including:
- Configuration file setup
- Environment variables
- Database connection test
- Email configuration test
- Browser session setup
- API credentials setup
- Scheduler instructions
"""

import os
import sys
import shutil
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from database import Database
from email_notifier import EmailNotifier
from scraper import AmazonScraper


def print_header(text):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_success(text):
    """Print a success message."""
    print(f"[SUCCESS] {text}")


def print_error(text):
    """Print an error message."""
    print(f"[ERROR] {text}")


def print_warning(text):
    """Print a warning message."""
    print(f"[WARNING] {text}")


def print_info(text):
    """Print an info message."""
    print(f"[INFO] {text}")


def check_config_file():
    """Check for and create config.yaml if it doesn't exist."""
    print_header("Step 1: Configuration File Setup")

    config_path = Path("config.yaml")
    example_path = Path("config.yaml.example")

    if not example_path.exists():
        print_error("config.yaml.example not found!")
        print_info("This file should be in the project root directory.")
        return False

    if config_path.exists():
        print_success("config.yaml already exists")
        print_info(f"Location: {config_path.absolute()}")

        response = input("\nDo you want to overwrite it? (y/N): ").lower()
        if response != 'y':
            print_info("Keeping existing config.yaml")
            return True

    # Copy example to config.yaml
    shutil.copy(example_path, config_path)
    print_success("Created config.yaml from config.yaml.example")
    print_info(f"Location: {config_path.absolute()}")

    return True


def prompt_config_edit():
    """Prompt user to edit configuration."""
    print_header("Step 2: Edit Configuration")

    print("You need to edit config.yaml with your settings:")
    print("\n  Required settings:")
    print("    - database.host, database.user, database.database")
    print("    - email.smtp_host, email.smtp_port")
    print("    - email.from_address, email.to_addresses")
    print("    - amazon.api_access_key, amazon.api_secret_key, amazon.api_associate_tag")
    print("\n  Optional settings:")
    print("    - deals.max_price (default: 4.00)")
    print("    - deals.min_discount_percent (default: 50)")
    print("    - scraping.headless (default: true)")

    print("\nPlease edit config.yaml now and press Enter when done...")
    input()
    print_success("Configuration updated")


def prompt_environment_variables():
    """Prompt user to set environment variables."""
    print_header("Step 3: Environment Variables")

    print("You need to set the following environment variables:")
    print("\n  1. MYSQL_PASSWORD - Your MySQL database password")
    print("  2. KINDLE_DEALS_PASSWORD - Your email account password")
    print("\nFor Gmail, you may need to create an App Password:")
    print("  https://support.google.com/accounts/answer/185833")

    print("\nExample (add to ~/.bashrc or ~/.zshrc):")
    print('  export MYSQL_PASSWORD="your-mysql-password"')
    print('  export KINDLE_DEALS_PASSWORD="your-email-password"')

    print("\nHave you set these environment variables? (y/N): ", end='')
    response = input().lower()

    if response != 'y':
        print_warning("Please set environment variables before continuing")
        print_info("You may need to restart your terminal after setting them")
        return False

    # Check if variables are actually set
    mysql_password = os.environ.get('MYSQL_PASSWORD')
    email_password = os.environ.get('KINDLE_DEALS_PASSWORD')

    if not mysql_password:
        print_error("MYSQL_PASSWORD environment variable not found")
        print_info("Please set it and run this script again")
        return False

    if not email_password:
        print_error("KINDLE_DEALS_PASSWORD environment variable not found")
        print_info("Please set it and run this script again")
        return False

    print_success("Environment variables are set correctly")
    return True


def test_database_connection(config):
    """Test MySQL database connection."""
    print_header("Step 4: Database Connection Test")

    try:
        print_info("Testing MySQL connection...")

        db = Database(
            host=config.get('database.host'),
            user=config.get('database.user'),
            password=config.get_mysql_password(),
            database=config.get('database.database')
        )

        print_success("Connected to MySQL successfully")
        print_success("Database tables created successfully")

        # Close connection
        db.close()

        return True

    except Exception as e:
        print_error(f"Database connection failed: {str(e)}")
        print_info("\nPossible issues:")
        print("  - MySQL server not running")
        print("  - Incorrect credentials in config.yaml")
        print("  - MYSQL_PASSWORD environment variable not set correctly")
        print("  - Database user doesn't have sufficient privileges")
        return False


def test_email_configuration(config):
    """Test email configuration (optional)."""
    print_header("Step 5: Email Configuration Test (Optional)")

    print("Would you like to test email configuration? (y/N): ", end='')
    response = input().lower()

    if response != 'y':
        print_info("Skipping email test")
        return True

    try:
        print_info("Testing SMTP connection...")

        notifier = EmailNotifier(
            smtp_server=config.get('email.smtp_host'),
            smtp_port=config.get('email.smtp_port'),
            from_address=config.get('email.from_address'),
            password=config.get_email_password()
        )

        # Send test email
        to_addresses = config.get('email.to_addresses', [])
        if not to_addresses:
            print_error("No recipient addresses configured in email.to_addresses")
            return False

        test_html = "<html><body><h1>Test Email</h1><p>Kindle Deals Monitor setup test successful!</p></body></html>"

        notifier.send_email(
            to_address=to_addresses[0],
            subject="Kindle Deals Monitor - Test Email",
            html_content=test_html
        )

        print_success("Test email sent successfully")
        print_info(f"Check {to_addresses[0]} for the test email")
        return True

    except Exception as e:
        print_error(f"Email test failed: {str(e)}")
        print_info("\nPossible issues:")
        print("  - Incorrect SMTP settings in config.yaml")
        print("  - KINDLE_DEALS_PASSWORD environment variable not set correctly")
        print("  - For Gmail: App Password not created or 2FA not enabled")
        print("  - SMTP server blocking connection")
        return False


def test_browser_session(config):
    """Test browser session setup (optional)."""
    print_header("Step 6: Browser Session Setup (Optional)")

    print("Would you like to test browser session setup? (y/N): ", end='')
    response = input().lower()

    if response != 'y':
        print_info("Skipping browser session test")
        return True

    try:
        print_info("Testing browser session setup...")
        print_info("This will open a browser window...")

        session_path = os.path.expanduser(config.get('storage.browser_session_path'))

        # Create session directory if it doesn't exist
        os.makedirs(os.path.dirname(session_path), exist_ok=True)

        with AmazonScraper(
            session_path=session_path,
            headless=False,  # Show browser for test
            page_timeout=config.get('scraping.page_load_timeout', 30000)
        ) as scraper:
            page = scraper.new_page()
            page.goto("https://www.amazon.com")

            print_success("Browser session created successfully")
            print_info(f"Session saved to: {session_path}")

            print("\nIf you want to save your Amazon login:")
            print("  1. Log in to Amazon in the browser window")
            print("  2. Press Enter when done to save the session")
            input()

        print_success("Browser session test completed")
        return True

    except Exception as e:
        print_error(f"Browser session test failed: {str(e)}")
        print_info("\nPossible issues:")
        print("  - Playwright not installed correctly")
        print("  - Browser dependencies missing")
        print("  - Run: playwright install chromium")
        return False


def print_api_setup_instructions():
    """Print Amazon Product Advertising API setup instructions."""
    print_header("Step 7: Amazon Product Advertising API Setup")

    print("To use the Amazon Product Advertising API:")
    print("\n  1. Join the Amazon Associates Program:")
    print("     https://affiliate-program.amazon.com/")
    print("\n  2. Get your API credentials:")
    print("     https://affiliate-program.amazon.com/assoc_credentials/home")
    print("\n  3. Update config.yaml with:")
    print("     - amazon.api_access_key: Your access key")
    print("     - amazon.api_secret_key: Your secret key")
    print("     - amazon.api_associate_tag: Your associate tag")
    print("     - amazon.api_region: Your region (US, UK, FR, DE, JP, etc.)")
    print("\n  Note: You need an approved Amazon Associates account to use the API")

    print_info("\nAPI credentials updated in config.yaml? (y/N): ", end='')
    response = input().lower()

    if response == 'y':
        print_success("API credentials configured")
    else:
        print_warning("Remember to update API credentials before using the monitor")


def print_scheduler_instructions():
    """Print cron/scheduler setup instructions."""
    print_header("Step 8: Scheduler Setup")

    project_dir = os.path.dirname(os.path.abspath(__file__))

    print("To run the Kindle Deals Monitor automatically, set up a cron job:")
    print("\n  1. Edit crontab:")
    print("     crontab -e")
    print("\n  2. Add the following line to run hourly:")
    print(f"     0 * * * * cd {project_dir} && /usr/bin/env python3 main.py >> ~/kindle-deals.log 2>&1")
    print("\n  3. Or run daily at 9 AM:")
    print(f"     0 9 * * * cd {project_dir} && /usr/bin/env python3 main.py >> ~/kindle-deals.log 2>&1")

    print("\n  Note: Make sure environment variables are set in cron environment:")
    print("     0 9 * * * export MYSQL_PASSWORD='...' && export KINDLE_DEALS_PASSWORD='...' && cd {project_dir} && python3 main.py")

    print("\n  Alternative: Use a systemd timer (Linux) or launchd (macOS)")
    print("\nFor manual runs:")
    print(f"  cd {project_dir}")
    print("  python3 main.py")


def print_completion_summary():
    """Print setup completion summary."""
    print_header("Setup Complete!")

    print("Next steps:")
    print("\n  1. Add books to monitor:")
    print("     - Edit your database to add book ASINs")
    print("     - Or use the API to add books programmatically")
    print("\n  2. Run the monitor:")
    print("     python3 main.py")
    print("\n  3. Set up automatic checks:")
    print("     - Configure cron job (see Step 8 above)")
    print("     - Or run manually as needed")

    print("\nConfiguration files:")
    print(f"  - Config: {os.path.abspath('config.yaml')}")
    print(f"  - Database: MySQL - {os.environ.get('USER', 'user')}@localhost")

    print("\nFor help and documentation:")
    print("  - README.md")
    print("  - docs/IMPLEMENTATION_PLAN.md")


def main():
    """Run the interactive setup wizard."""
    print("\n" + "*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  Kindle Deals Monitor - Interactive Setup Wizard".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)

    # Step 1: Check/create config file
    if not check_config_file():
        print_error("Setup failed: Could not create config.yaml")
        sys.exit(1)

    # Step 2: Prompt to edit config
    prompt_config_edit()

    # Step 3: Check environment variables
    if not prompt_environment_variables():
        print_error("Setup incomplete: Environment variables not set")
        print_info("Set the required environment variables and run setup.py again")
        sys.exit(1)

    # Load configuration
    try:
        config = Config("config.yaml")
    except Exception as e:
        print_error(f"Failed to load config.yaml: {str(e)}")
        print_info("Please check your configuration file for errors")
        sys.exit(1)

    # Step 4: Test database connection
    if not test_database_connection(config):
        print_error("Setup incomplete: Database connection failed")
        print_info("Fix database configuration and run setup.py again")
        sys.exit(1)

    # Step 5: Test email configuration (optional)
    test_email_configuration(config)

    # Step 6: Test browser session (optional)
    test_browser_session(config)

    # Step 7: API setup instructions
    print_api_setup_instructions()

    # Step 8: Scheduler instructions
    print_scheduler_instructions()

    # Completion summary
    print_completion_summary()

    print("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Setup cancelled by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
