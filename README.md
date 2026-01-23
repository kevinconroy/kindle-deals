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
python src/check_deals.py

# Test email notification
python src/send_notification.py --test
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and update with your settings, including:
- MySQL database credentials
- Email SMTP settings and password
- Amazon Product Advertising API credentials
