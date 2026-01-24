# Kindle Deals Monitor

Monitor Kindle samples for price deals and receive email notifications.

## Setup

One-line setup:

```bash
./setup.sh
```

Then activate the virtual environment:

```bash
source venv/bin/activate
```

After setup, edit `config.yaml` with your settings (MySQL credentials, email, Amazon API keys).

## Usage

```bash
# First time: Login and save session
python src/sync_library.py --login

# Sync your Kindle library (after login)
python src/sync_library.py

# Check for deals
# Note: Books already owned (showing "Read Now") are automatically marked as inactive
python src/check_deals.py

# Send email for recent deals (without re-checking)
python src/check_deals.py --send-notification

# Test email notification
python src/send_notification.py --test
```

## Features

- **Automatic library sync** - Scrapes ASINs from your Amazon "My Books" page
- **Smart deal detection** - Finds books under $4 or 50% off
- **Owned book detection** - Automatically removes books you've already purchased
- **Email notifications** - Get notified when deals are found
- **Price history tracking** - Stores price changes in MySQL database

## Configuration

Copy `config.yaml.example` to `config.yaml` and update with your settings, including:
- MySQL database credentials
- Email SMTP settings and password

Note: This tool uses web scraping instead of Amazon's API to avoid eligibility requirements.
