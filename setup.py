#!/usr/bin/env python3
"""
Non-interactive setup script for Kindle Deals Monitor.

Handles:
- Configuration file setup
- Database table creation
"""

import os
import sys
import shutil
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from database import Database


def setup_config_file():
    """Create config.yaml from example if it doesn't exist."""
    config_path = Path("config.yaml")
    example_path = Path("config.yaml.example")

    if not example_path.exists():
        print("ERROR: config.yaml.example not found!")
        return False

    if config_path.exists():
        print("✓ config.yaml already exists")
        return True

    # Copy example to config.yaml
    shutil.copy(example_path, config_path)
    print("✓ Created config.yaml from config.yaml.example")
    print()
    print("IMPORTANT: Edit config.yaml with your settings:")
    print("  - database.host, database.user, database.password, database.database")
    print("  - email.smtp_server, email.smtp_port, email.from_address, email.to_address, email.password")
    print("  - amazon.api_access_key, amazon.api_secret_key, amazon.api_associate_tag")
    print()

    return True


def setup_database(config):
    """Create database tables."""
    try:
        print("Setting up database...")

        db = Database(
            host=config.get('database.host'),
            user=config.get('database.user'),
            password=config.get('database.password'),
            database=config.get('database.database')
        )

        print("✓ Connected to MySQL successfully")
        print("✓ Database tables created successfully")

        db.close()
        return True

    except Exception as e:
        print(f"ERROR: Database setup failed: {str(e)}")
        print()
        print("Possible issues:")
        print("  - MySQL server not running")
        print("  - Incorrect credentials in config.yaml")
        print("  - Database user doesn't have sufficient privileges")
        return False


def main():
    """Run the setup."""
    print()
    print("=" * 60)
    print("  Kindle Deals Monitor - Setup")
    print("=" * 60)
    print()

    # Step 1: Check/create config file
    if not setup_config_file():
        print("ERROR: Setup failed - could not create config.yaml")
        sys.exit(1)

    # Step 2: Load configuration
    try:
        config = Config("config.yaml")
    except Exception as e:
        print(f"ERROR: Failed to load config.yaml: {str(e)}")
        print("Please check your configuration file for errors")
        sys.exit(1)

    # Step 3: Setup database
    if not setup_database(config):
        print("ERROR: Setup incomplete - database setup failed")
        print("Fix database configuration in config.yaml and run setup.py again")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Sync your Kindle library: python src/sync_library.py")
    print("  2. Check for deals: python src/check_deals.py")
    print("  3. Test email: python src/send_notification.py --test")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
